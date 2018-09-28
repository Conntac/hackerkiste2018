import traceback

import curio
from curio import socket
import google.protobuf.json_format

from ..proto import commands_pb2 as commands, events_pb2 as events, Protocol, recv_len
from .. import util


class Rules:
	def __init__(self):
		pass


class Client:
	def __init__(self, host, port, protocol):
		self.host = host
		self.port = port
		self.protocol = protocol
		self.queue = curio.Queue()

	async def run(self):
		sock = await curio.open_connection(self.host, self.port)
		try:
			async with util.ScopeTask(self.queue_handler(sock)):
				while True:
					packet_length = int.from_bytes(await recv_len(sock, 4), 'big')
					packet = await recv_len(sock, packet_length)
					#print(">", packet)
					print
					try:
						message = events.ServerToClient()
						message.ParseFromString(packet)
						payload = getattr(message, message.WhichOneof("payload"))
						await self.protocol.handle(None, self, payload)
					except:
						traceback.print_exc()
		except ConnectionResetError:
			await sock.close()
			await self.protocol.on_disconnect(None, self)

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
	def __init__(self, rules):
		super(ProtocolUser, self).__init__()
		self.rules = rules

	@Protocol.handler(events.InfoResourceType)
	async def on_info_resource_type(self, server, client, message):
		print(f"ResourceType {message.resource_type_id} is {message.resource_type.name}")

	@Protocol.handler(events.InfoTerrainType)
	async def on_info_terrain_type(self, server, client, message):
		print(f"TerrainType {message.terrain_type_id} is {message.terrain_type.name}")

	@Protocol.handler(events.InfoActionType)
	async def on_info_action_type(self, server, client, message):
		print(f"ActionType {message.action_type_id} is {message.action_type.name}")

	@Protocol.handler(events.InfoUnitType)
	async def on_info_unit_type(self, server, client, message):
		print(f"UnitType {message.unit_type_id} is {message.unit_type.name}")

	@Protocol.handler(events.EventMapGenerate)
	async def on_map_generate(self, server, client, message):
		pass

	@Protocol.handler(events.EventMapGenerateCell)
	async def on_map_generate_cell(self, server, client, message):
		pass

	@Protocol.handler(events.EventGameStart)
	async def on_game_start(self, server, client, message):
		print("The game is starting!")

	@Protocol.handler(events.EventPlayerResource)
	async def on_player_resource(self, server, client, message):
		print(f"You have resource {message.resource_type_id} x{message.amount}")

	@Protocol.handler(events.EventUnitCreate)
	async def on_unit_create(self, server, client, message):
		print(f"unit {message.unit_id} of type {message.unit_type_id} created for {message.player_id}")

	async def on_unhandled(self, server, client, message):
		print(message.DESCRIPTOR.name, google.protobuf.json_format.MessageToJson(message))

	async def on_disconnect(self, server, client):
		print("Lost connection to server.")
		raise SystemExit(1)
