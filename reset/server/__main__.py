#!/usr/bin/python3

import curio

from . import ProtocolPreGame, Server
from .rules import *
from .generator import *
from .game import Payment

rules = Rules()

terrain_grass = rules.terrain_types.create("grass", "Grass", {"walk", "build"})
terrain_mountain = rules.terrain_types.create("mountain", "Mountains", set())
terrain_water = rules.terrain_types.create("water", "Water", {"water"})

resource_wood = rules.resource_types.create("wood", "Wood", 100)
resource_food = rules.resource_types.create("food", "Food", 100)
resource_stone = rules.resource_types.create("stone", "Stone", 100)

def action_create_near(unit_type):
	async def execute(map, action):
		async with Payment(action.player, action.action_type.cost):
			await curio.sleep(action.action_type.duration)
			await map.create_unit_near(action.unit, unit_type, action.player)
	return execute

def action_farm(farm_resources):
	async def execute(map, action):
		await curio.sleep(action.action_type.duration)
		await action.unit.player.give(farm_resources)
	return execute

async def execute_move_towards(map, action):
	## TODO: 
	pass


unit_forest = rules.unit_types.create("forest", "Forest", {"resource", "resource_wood"})
unit_quarry = rules.unit_types.create("quarry", "Quarry", {"resource", "resource_quarry"})
unit_city = rules.unit_types.create("city", "City", {"building"})
unit_citizen = rules.unit_types.create("citizen", "Citizen", set())

#action_citizen_move_towards = runes.action_types.create(execute_move_towards, "citizen_move_towards", "Move", unit_citizen, duration=0.5, target_type=ActionTargetType.CELL, target_tags={"walk"})
action_citizen_farm_wood = rules.action_types.create(action_farm({resource_wood: 10}), "citizen_farm_wood", "Cut down trees", unit_citizen, duration=2.0, target_type=ActionTargetType.UNIT, target_tags={"resource_wood"})
action_city_create_citizen = rules.action_types.create(action_create_near(unit_citizen), "city_create_citizen", "Create a Citizen", unit_city, {resource_food: 20}, 2.0)

gen = Generator()

noise_terrain = gen.add_pass(NoisePass({'scale_x': 100.0, 'scale_y': 100.0, 'distribution': 'uniform'}))
noise_terrain.add_hook(hook_terrain(terrain_grass, 0.0, 0.5))
noise_terrain.add_hook(hook_terrain(terrain_mountain, 0.5, 0.6))
noise_terrain.add_hook(hook_terrain(terrain_water, 0.6, 1.0 + 1))

noise_resources = gen.add_pass(NoisePass({'scale_x': 100.0, 'scale_y': 100.0, 'distribution': 'uniform'}))
noise_resources.add_hook(hook_resource(unit_forest, 0.0, 0.05, {"build"}))
noise_resources.add_hook(hook_resource(unit_quarry, 0.2, 0.25, {"build"}))

player_bases = gen.add_pass(PlayerBasePass())
player_bases.add_hook(hook_player_unit(unit_city))

async def main():
	protocol = ProtocolPreGame(rules, gen)
	server = Server('0.0.0.0', 1337)
	await server.set_protocol(protocol)
	async with curio.TaskGroup() as g:
		await g.spawn(server.run())


if __name__ == '__main__':
	curio.run(main())

