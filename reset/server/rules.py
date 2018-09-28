import enum

import curio

from .. import util


class TerrainType:
	def __init__(self, id, name, description, tags):
		self.id = id
		self.name = name
		self.description = description
		self.tags = tags

	def __str__(self):
		return f"T{{{self.name}}}"


class ResourceType:
	def __init__(self, id, name, description, start_value):
		self.id = id
		self.name = name
		self.description = description
		self.start_value = start_value

	def __str__(self):
		return f"R{{{self.name}}}"


class ActionMode(enum.Enum):
	ONCE = 0
	REPEAT = 1


class ActionTargetType(enum.Enum):
	NONE = 0
	CELL = 1
	UNIT = 2


class ActionState(enum.Enum):
	QUEUED = 0
	WORKING = 1
	COMPLETE = 2
	WAIT = 3
	CANCELLED = 4
	FAILED = 5


class Action:
	def __init__(self, id, action_type, unit, mode, target_unit=None, target_cell=None):
		self.id = id
		self.action_type = action_type
		self.unit = unit
		self.mode = mode
		self.target_unit = target_unit
		self.target_cell = target_cell

	@property
	def player(self):
		return self.unit.player


class ActionType:
	def __init__(self, id, executor, name, description, unit_type, cost=None, duration=0.0, default_mode=ActionMode.ONCE, target_type=ActionTargetType.NONE, target_tags=None):
		self.id = id
		self.executor = executor
		self.name = name
		self.description = description
		self.unit_type = unit_type
		self.cost = cost or {}
		self.duration = duration
		self.default_mode = default_mode
		self.target_type = target_type
		self.target_tags = target_tags or set()

	def __str__(self):
		return f"A{{{self.name}}}"


class UnitType:
	def __init__(self, id, name, description, tags, default_action_type=None):
		self.id = id
		self.name = name
		self.description = description
		self.tags = tags
		self.default_action_type = default_action_type

	def __str__(self):
		return f"U{{{self.name}}}"


class Rules:
	def __init__(self):
		self.terrain_types = util.IdList(TerrainType)
		self.resource_types = util.IdList(ResourceType)
		self.action_types = util.IdList(ActionType)
		self.unit_types = util.IdList(UnitType)
		self.events = curio.Queue()


