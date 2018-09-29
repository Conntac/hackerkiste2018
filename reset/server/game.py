import enum
import itertools
import traceback

import curio

from . import util
from .rules import *


class GameError(Exception):
	def __init__(self, message):
		self.message = message


class ResourceError(GameError):
	def __init__(self, resource, got, need):
		super(ResourceError, self).__init__(f"Not enough {resource.name} (got {got}, need {need})")


class OwnerError(GameError):
	def __init__(self, unit):
		super(OwnerError, self).__init__(f"The unit {unit.id} ({unit.unit_type.name}) can only be controlled by {unit.player.name}")


class ActionError(GameError):
	def __init__(self, state, message):
		super(ActionError, self).__init__(message)
		self.state = state


class Value:
	def __init__(self, value):
		self._value = value
		self._event = curio.Event()

	@property
	def value(self):
		return self._value

	async def set(self, value):
		self._value = value
		await self._event.set()
		self._event.clear()

	async def wait(self):
		await self._event.wait()


class Player:
	def __init__(self, id, name, client):
		self.id = id
		self.name = name
		self.client = client
		self.resources = {}

	async def wait_resources(self, resources):
		'''Wait until the player has the specified resources.'''
		while True:
			unsatisfied_resource = None
			for resource, need in resources.items():
				if self.resources.setdefault(resource, Value(0))._value < need:
					unsatisfied_resource = resource
					break
			if unsatisfied_resource is None:
				return True
			else:
				while self.resources[unsatisfied_resource]._value < resources[unsatisfied_resource]:
					await self.resources[unsatisfied_resource]._event.wait()

	async def take(self, pay_resources):
		'''Deduct the specified resources from the player.
		If the requested resources are available, the method deducts them and returns.
		If the requested resources are not available, the method raises a ResourceError without deducting any resources.
		The operation is atomic with respect to any observers of the resource's Value instances'''
		for resource, need in pay_resources.items():
			if self.resources.setdefault(resource, Value(0))._value < need:
				raise ResourceError(resource, self.resources[resource]._value, need)
		for resource, need in pay_resources.items():
			self.resources[resource]._value -= need
		for resource in pay_resources:
			await self.resources[resource]._event.set()
			self.resources[resource]._event.clear()

	async def give(self, get_resources):
		for resource, need in get_resources.items():
			self.resources[resource]._value += need
		for resource in get_resources:
			await self.resources[resource]._event.set()
			self.resources[resource]._event.clear()


class Payment:
	'''Usage:

		async with Payment(player, {resource: amount, ...}):
			await work()

	When the async-with block is entered, the resources are deducted from the player if possible.
	If the player does not have enough resources, the with statement raises a ResourceError.
	If the with block does not raise an exception, the resources stay deducted.
	If the with block does raise an exception, the resources are returned before the block is exited.'''
	def __init__(self, player, resources):
		self.player = player
		self.resources = resources

	async def __aenter__(self):
		await self.player.take(self.resources)

	async def __aexit__(self, exc_type, exc_value, exc_traceback):
		if exc_type is not None:
			await self.player.give(self.resources)


class Unit:
	def __init__(self, id, unit_type, map, player):
		self.id = id
		self.unit_type = unit_type
		self.map = map
		self.player = player
		self._task_group = curio.TaskGroup()
		self._semaphore = curio.Semaphore()  # tasks will acquire the semaphore in the same order as they call acquire().
		self._action_tasks = {}

	async def _process(self, action):
		try:
			state = ActionState.QUEUED
			async def put_state(st, msg=None):
				nonlocal state
				state = st
				await self.map.events.put(('ACTION_UPDATE', action, st, msg))
			while True:
				async with self._semaphore:  # Wait for our turn...
					try:
						await put_state(ActionState.WORKING)
						await action.action_type.executor(self.map, action)  # Do the work (e.g. deduct resources, delay for duration)
						await put_state(ActionState.COMPLETE)
					except ResourceError as err:
						await put_state(ActionState.WAIT, f"Action {action.id} ({action.action_type.name}) is waiting: {err.message}")
					except ActionError as err:
						await put_state(err.state, err.message)
					except curio.TaskCancelled:
						await put_state(ActionState.CANCELLED)
					except:
						traceback.print_exc()
						await put_state(ActionState.FAILED, "Unknown error, check the server logs")
						return
				if state == ActionState.WAIT:
					await action.unit.player.wait_resources(action.action_type.cost) # Wait for resources
				elif state == ActionState.FAILED:
					return # It's a permanent fail, so it's over
				elif state == ActionState.COMPLETE:
					if action.mode == ActionMode.REPEAT:
						await put_state(ActionState.QUEUED)
					else:
						return
		finally:
			await self.map.events.put(('ACTION_DEQUEUE', action))

	async def queue_action(self, action):
		self._action_tasks[action.id] = await self._task_group.spawn(self._process(action))

	async def cancel_action(self, action_or_id):
		action = self.map.actions.resolve(action_or_id)
		task = self._action_tasks.pop(action.id)
		await task.cancel()

	async def cancel_all(self):
		self._task_group.cancel_remaining()
		self._action_tasks.clear()

	def __str__(self):
		return str(self.unit_type)


class Cell:
	def __init__(self, terrain_type, unit=None):
		self.terrain_type = terrain_type
		self.unit = unit

	def __str__(self):
		return f"[{self.terrain_type}{self.unit if self.unit is not None else ''}]"


class Map:
	def __init__(self, players, width, height):
		self.width = width
		self.height = height
		self.cells = [Cell(None) for i in range(width * height)]

		self.players = players  # already a util.IdList(Player)
		self.units = util.IdList(Unit)
		self.actions = util.IdList(Action)

		self.events = curio.Queue()

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

	def __str__(self):
		return f"Map({self.width}x{self.height}){{\n" + '\n'.join(
			''.join(str(self[(x,y)]) for x in range(self.width))
			for y in range(self.height)
		) + "}"

	def get_location(self, unit):
		for i, c in enumerate(self.cells):
			if c.unit == unit:
				return i % self.width, i // self.width

	async def create_unit(self, xy, unit_type, player):
		unit = self.units.create(unit_type, self, player)
		cell = self[xy]
		cell.unit = unit
		await self.events.put(('UNIT_CREATE', xy, unit))
		return unit

	async def create_unit_near(self, unit, unit_type, player):
		for pos in vicinity(self.get_location(unit), self.width, self.height):
			if self[pos].unit is None:
				return await self.create_unit(pos, unit_type, player)

	async def action_queue(self, action_type, unit, mode, target_unit, target_cell):
		action = self.actions.create(action_type, unit, mode, target_unit, target_cell)
		await unit.queue_action(action)
		return action

	async def move_unit(self, unit, destination):
		cell = self[destination]
		if 'walk' not in cell.terrain_type.tags:
			raise GameError("cannot move unit to unwalkable cell")
		unit_pos = self.get_location(unit)
		if abs(unit_pos[0] - destination[0]) > 1 or abs(unit_pos[1] - destination[1]) > 1:
			raise GameError("can only move unit to neighboring cell")
		if cell.unit is not None:
			raise GameError("cells can only hold one unit")
		cell.unit = unit
		self[unit_pos].unit = None
		await self.events.put(('UNIT_MOVE', unit, destination))



def vicinity(xy, width, height):
	'''Generate coordinates starting at xy and gradually moving further away
	in a spiral pattern. Useful if you need to find an empty cell near a
	certain position.'''

	def inside(xy):
		return 0 <= xy[0] < width and 0 <= xy[1] < height

	x, y = xy
	yield (x, y)
	for distance in itertools.count(1):
		points = [(x + i, y - distance + i) for i in range(distance)]
		points.extend((x + distance - i, y + i) for i in range(distance))
		points.extend((x - i, y + distance - i) for i in range(distance))
		points.extend((x - distance + i, y - i) for i in range(distance))
		points = list(filter(inside, points))
		if not points:
			break
		yield from points
