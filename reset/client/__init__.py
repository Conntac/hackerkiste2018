import logging

import curio
import curio.traps
from curio import socket
import google.protobuf.json_format
import termbox

from ..proto import commands_pb2 as commands, events_pb2 as events, Protocol, recv_len
from .. import util
from .ui import Ui, TermboxAsync


class Rules:
	def __init__(self):
		self.resource_types = {}
		self.terrain_types = {}
		self.unit_types = {}
		self.action_types = {}


class Cell:
	def __init__(self, terrain_type, unit=None):
		self.terrain_type = terrain_type
		self.unit = unit

	def __str__(self):
		return f"[{self.terrain_type}{self.unit if self.unit is not None else ''}]"


class Map:
	def __init__(self, width, height):
		self.width = width
		self.height = height
		self.cells = [Cell(None) for i in range(width * height)]
		self.units = {}
		self.actions = {}

	def __getitem__(self, xy):
		x, y = xy
		if not (0 <= x < self.width) or not (0 <= y < self.height):
			raise LookupError("Coordinates are outside the map")
		return self.cells[y * self.width + x]

	def __iter__(self):
		for i, cell in enumerate(self.cells):
			if cell is None:
				continue
			yield (i % self.width, i // self.width), cell


class Client:
	def __init__(self, logger, host, port, rules, protocol):
		self.logger = logger
		self.host = host
		self.port = port
		self.protocol = protocol
		self.queue = curio.Queue()
		self.rules = rules
		self.tb = None
		self.map = None
		self.ui = Ui(self)

	async def command_join(self, args):
		name = args[0] if args else "Player"
		await self.send(commands.CmdJoin(name=name))

	async def command_start(self, args):
		await self.send(commands.CmdGameStart())

	async def command_action(self, args):
		ap = argparse.ArgumentParser()
		ap.add_argument("action_type", type=int)
		ap.add_argument("unit", type=int)
		ap.add_argument("--target", "-t", type=int, default=None)
		ap.add_argument("-x", type=int, default=None)
		ap.add_argument("-y", type=int, default=None)
		args = ap.parse_args(args)
		cmd = commands.CmdActionQueue(action_type_id=args.action_type, unit_id=args.unit)
		if args.target is not None:
			cmd.target_unit_id = args.target
		if args.x is not None and args.y is not None:
			cmd.target_cell.x = args.x
			cmd.target_cell.y = args.y
		await self.send(cmd)

	async def run_command(self, command, args):
		handler = getattr(self, 'command_'+command, None)
		if handler is not None:
			await handler(args)
		else:
			self.logger.warning(f"No such command {command!r}");

	async def _run_net(self):
		sock = await curio.open_connection(self.host, self.port)
		try:
			async with util.ScopeTask(self.queue_handler(sock)):
				while True:
					packet_length = int.from_bytes(await recv_len(sock, 4), 'big')
					packet = await recv_len(sock, packet_length)
					#print(">", packet)
					try:
						message = events.ServerToClient()
						message.ParseFromString(packet)
						payload = getattr(message, message.WhichOneof("payload"))
						await self.protocol.handle(None, self, payload)
					except:
						self.logger.exception("Error handling network packet")
		except ConnectionResetError:
			await sock.close()
			await self.protocol.on_disconnect(None, self)

	async def _run_input(self):
		async for event in self.tb:
			etype, ch, key, mod, w, h, xx, yy = event
			if etype == termbox.EVENT_KEY:
				if key == termbox.KEY_CTRL_C:
					raise KeyboardInterrupt()
				else:
					try:
						await self.ui.on_key(self.tb, key, ch, mod)
					except:
						self.logger.exception(f"Error handling terminal event {event!r}")
			elif etype == termbox.EVENT_RESIZE:
				pass  # we use .width() and .height() anyway
			else:
				self.logger.warning(f"Unhandled event {event!r}")

	async def _run_output(self):
		while True:
			self.tb.clear()
			await self.ui.render(self.tb, 0, 0, self.tb.width(), self.tb.height())
			self.tb.present()
			await curio.sleep(1/30.0)

	async def run(self):
		async with TermboxAsync() as tb:
			self.tb = tb
			async with curio.TaskGroup() as g:
				await g.spawn(self._run_net())
				await g.spawn(self._run_input())
				await g.spawn(self._run_output())

	async def queue_handler(self, sock):
		while True:
			payload = await self.queue.get()
			message = commands.ClientToServer()
			for fd in message.DESCRIPTOR.oneofs_by_name["payload"].fields:
				if payload.DESCRIPTOR == fd.message_type:
					getattr(message, fd.name).CopyFrom(payload)
			packet = message.SerializeToString()
			#print("<", packet)
			await sock.sendall(len(packet).to_bytes(4, 'big'))
			await sock.sendall(packet)

	async def send(self, message):
		await self.queue.put(message)


class ProtocolUser(Protocol):
	def __init__(self, logger):
		self.logger = logger
		super(ProtocolUser, self).__init__()

	@Protocol.handler(events.InfoResourceType)
	async def on_info_resource_type(self, server, client, message):
		client.rules.resource_types[message.resource_type_id] = message.resource_type
		self.logger.debug(f"ResourceType {message.resource_type_id} is {message.resource_type.name}")

	@Protocol.handler(events.InfoTerrainType)
	async def on_info_terrain_type(self, server, client, message):
		client.rules.terrain_types[message.terrain_type_id] = message.terrain_type
		self.logger.debug(f"TerrainType {message.terrain_type_id} is {message.terrain_type.name}")

	@Protocol.handler(events.InfoActionType)
	async def on_info_action_type(self, server, client, message):
		client.rules.action_types[message.action_type_id] = message.action_type
		self.logger.debug(f"ActionType {message.action_type_id} is {message.action_type.name}")

	@Protocol.handler(events.InfoUnitType)
	async def on_info_unit_type(self, server, client, message):
		client.rules.unit_types[message.unit_type_id] = message.unit_type
		self.logger.debug(f"UnitType {message.unit_type_id} is {message.unit_type.name}")

	@Protocol.handler(events.EventMapGenerate)
	async def on_map_generate(self, server, client, message):
		client.map = Map(message.width, message.height)
		self.logger.debug(f"Map is {message.width}x{message.height}")

	@Protocol.handler(events.EventMapGenerateCell)
	async def on_map_generate_cell(self, server, client, message):
		client.map[message.position.x, message.position.y].terrain_type = client.rules.terrain_types[message.terrain_type_id]
		self.logger.debug(f"Map ({message.position.x}, {message.position.y}) is terrain type {message.terrain_type_id}")

	@Protocol.handler(events.EventGameStart)
	async def on_game_start(self, server, client, message):
		self.logger.info("The game is starting!")

	@Protocol.handler(events.EventPlayerResource)
	async def on_player_resource(self, server, client, message):
		self.logger.debug(f"You have resource {message.resource_type_id} x{message.amount}")

	@Protocol.handler(events.EventUnitCreate)
	async def on_unit_create(self, server, client, message):
		self.logger.debug(f"unit {message.unit_id} of type {message.unit_type_id} created for {message.player_id}")

	async def on_unhandled(self, server, client, message):
		self.logger.debug(f"{message.DESCRIPTOR.name} {google.protobuf.json_format.MessageToJson(message)}")

	async def on_disconnect(self, server, client):
		self.logger.debug("Lost connection to server.")
		raise SystemExit(1)
