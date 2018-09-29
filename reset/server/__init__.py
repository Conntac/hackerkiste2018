import math
import random
import traceback

import curio
from curio import socket

from ..proto import commands_pb2 as commands, events_pb2 as events, types_pb2 as types, Protocol
from .. import util
from . import game


class Client:
	def __init__(self):
		self.player = None
		self._task_group = curio.TaskGroup()

	async def close(self):
		raise NotImplementedError()

	async def send(self, packet):
		raise NotImplementedError()

	async def watch_player(self, player):
		for resource_type, resource_value in player.resources.items():
			async def watcher(resource_type, resource_value):
				while True:
					await resource_value.wait()
					await self.send(events.EventPlayerResource(resource_type_id=resource_type.id, amount=resource_value.value))
			await self._task_group.spawn(watcher(resource_type, resource_value))


class Server:
	def __init__(self, protocol):
		self.protocol = protocol
		self.clients = set()
		self._protocol_task = None

	async def add_client(self, client):
		self.clients.add(client)

	async def remove_client(self, client):
		self.clients.discard(client)

	async def set_protocol(self, protocol):
		if self._protocol_task is not None:
			await self._protocol_task.cancel()
		self.protocol = protocol
		if self.protocol is not None:
			self._protocol_task = await curio.spawn(self.protocol.run(self))
		else:
			self._protocol_task = None

	async def run(self):
		if self.protocol is not None:
			self._protocol_task = await curio.spawn(self.protocol.run(self))

	async def handle(self, client, message):
		await self.protocol.handle(self, client, message)

	async def broadcast(self, message):
		for client in self.clients:
			await client.send(message)


class ProtocolPreGame(Protocol):
	def __init__(self, rules, generator):
		super(ProtocolPreGame, self).__init__()
		self.rules = rules
		self.generator = generator
		self.players = util.IdList(game.Player)

	async def run(self, server):
		pass

	async def handle(self, server, client, message):
		try:
			return await super(ProtocolPreGame, self).handle(server, client, message)
		except game.GameError as e:
			await client.send(events.Error(error=e.message))

	@Protocol.handler(commands.CmdJoin)
	async def on_command_join(self, server, client, message):
		if client.player is None:
			client.player = self.players.create(message.name, client)
			client.player.resources = {resource_type: game.Value(resource_type.start_value) for resource_type in self.rules.resource_types}
			await server.broadcast(events.EventPlayerJoin(player_id=client.player.id, name=client.player.name))
			print(f"Player joined: {client.player.name!r}")
		else:
			await client.send(events.Error(error="You already joined; I'm ignoring this second CmdJoin."))

	@Protocol.handler(commands.CmdLeave)
	async def on_command_leave(self, server, client, message):
		if client.player is not None:
			self.players.destroy(client.player)
			print(f"Player left: {client.player.name!r}")
			client.player = None
		else:
			await client.send(events.Error(error="You haven't joined; I'm ignoring this CmdLeave."))

	@Protocol.handler(commands.CmdGameStart)
	async def on_command_game_start(self, server, client, message):
		await self._send_rules(server, self.rules)
		map = await self.generator.generate(self.players)
		await server.set_protocol(ProtocolGame(self.rules, map))
		print("Starting game")
		for player in map.players:
			await player.client.watch_player(player)
		await server.broadcast(events.EventGameStart())

	async def _send_rules(self, server, rules):
		for terrain_type in rules.terrain_types:
			info = events.InfoTerrainType()
			info.terrain_type_id = terrain_type.id
			info.terrain_type.name = terrain_type.name
			info.terrain_type.description = terrain_type.description
			info.terrain_type.tags[:] = terrain_type.tags
			await server.broadcast(info)
		for resource_type in rules.resource_types:
			info = events.InfoResourceType()
			info.resource_type_id = resource_type.id
			info.resource_type.name = resource_type.name
			info.resource_type.description = resource_type.description
			await server.broadcast(info)
		for unit_type in rules.unit_types:
			info = events.InfoUnitType()
			info.unit_type_id = unit_type.id
			info.unit_type.name = unit_type.name
			info.unit_type.description = unit_type.description
			info.unit_type.default_action_type_id = unit_type.default_action_type.id if unit_type.default_action_type is not None else 0
			info.unit_type.tags[:] = unit_type.tags
			await server.broadcast(info)
		for action_type in rules.action_types:
			info = events.InfoActionType()
			info.action_type_id = action_type.id
			info.action_type.name = action_type.name
			info.action_type.description = action_type.description
			info.action_type.unit_type_id = action_type.unit_type.id
			for res, value in action_type.cost.items():
				res_cost = info.action_type.cost.add()
				res_cost.resource_type_id = res.id
				res_cost.amount = value
			info.action_type.duration = action_type.duration
			info.action_type.default_mode = action_type.default_mode.value
			info.action_type.target_type = action_type.target_type.value
			info.action_type.target_tags[:] = action_type.target_tags
			await server.broadcast(info)


class ProtocolGame(Protocol):
	def __init__(self, rules, map):
		super(ProtocolGame, self).__init__()
		self.rules = rules
		self.map = map

	async def run(self, server):
		while True:
			event = await self.map.events.get()
			handler = self.get_handler(event[0])
			await handler(server, None, event[1:])

	async def handle(self, server, client, message):
		try:
			return await super(ProtocolGame, self).handle(server, client, message)
		except game.GameError as e:
			await client.send(events.Error(error=e.message))

	@Protocol.handler('MAP')
	async def on_event_map(self, server, client, event):
		map, = event
		event = events.EventMapGenerate(width=map.width, height=map.height)
		await server.broadcast(event)

	@Protocol.handler('MAP_CELL')
	async def on_event_map_cell(self, server, client, event):
		xy, terrain_type = event
		event = events.EventMapGenerateCell(terrain_type_id=terrain_type.id)
		event.position.x, event.position.y = xy
		await server.broadcast(event)

	@Protocol.handler('UNIT_CREATE')
	async def on_event_unit_create(self, server, client, event):
		xy, unit = event
		event = events.EventUnitCreate()
		event.unit_id = unit.id
		event.player_id = unit.player.id if unit.player else 0
		event.unit_type_id = unit.unit_type.id
		event.position.x, event.position.y = xy
		await server.broadcast(event)

	@Protocol.handler('UNIT_MOVE')
	async def on_event_unit_move(self, server, client, event):
		unit, xy = event
		event = events.EventUnitMove(unit_id=unit.id)
		event.position.x, event.position.y = xy
		await server.broadcast(event)

	@Protocol.handler('ACTION_UPDATE')
	async def on_action_update(self, server, client, event):
		action, state, msg = event
		event = events.EventActionUpdate(action_id=action.id, state=state.value)
		if msg is not None:
			event.message = msg
		await action.unit.player.client.send(event)

	@Protocol.handler('ACTION_DEQUEUE')
	async def on_action_dequeue(self, server, client, event):
		action, = event
		await action.unit.player.client.send(events.EventActionDequeued(action_id=action.id))

	@Protocol.handler(commands.CmdLeave)
	async def on_command_leave(self, server, client, message):
		self.map.players.destroy(client.player)
		await client.close()
		for unit in self.map.units:
			self.map.reposess(unit, 0)

	@Protocol.handler(commands.CmdActionQueue)
	async def on_command_action_queue(self, server, client, message):
		action_type = self.rules.action_types.get(message.action_type_id)
		unit = self.map.units.get(message.unit_id)
		target_unit = None if not message.HasField("target_unit_id") else self.map.units.get(message.target_unit_id)
		target_cell = None if not message.HasField("target_cell") else (message.target_cell.x, message.target_cell.y)

		if unit.player != client.player:
			raise game.GameError("You're not allowed to manage that unit")
		if action_type.unit_type != unit.unit_type:
			raise game.GameError("This action type cannot be performed by this unit.")
		if target_unit is not None:
			if action_type.target_type != rules.ActionTargetType.UNIT:
				raise game.GameError("This action does not work on units")
			if not action_type.target_tags <= target_unit.tags:
				raise game.GameError("Target unit does not have the necessary tags")
		if target_cell is not None:
			if action_type.target_type != rules.ActionTargetType.CELL:
				raise game.GameError("This action does not work on cells")
			if not (0 <= target_cell[0] < self.map.width and 0 <= target_cell[1] < self.map.height):
				raise game.GameError("Target cell is not inside the map")
			if not action_type.target_tags <= self.map[target_cell].terrain_type.tags:
				raise game.GameError("Target cell does not have the necessary tags")

		action = await self.map.action_queue(action_type, unit, message.mode, target_unit, target_cell)
		await client.send(events.EventActionQueued(action_id=action.id, unit_id=action.unit.id))

	@Protocol.handler(commands.CmdActionCancel)
	async def on_command_action_cancel(self, server, client, message):
		pass 
