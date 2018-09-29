import math
import random

import noise

from . import game


MAP_AREA_PER_PLAYER = 20*20-1  # rounding will give us 21x21 otherwise


def gaussian_cdf(mu, sigma):
	invscale = sigma * math.sqrt(2)  #precalculate a constant

	def f(x):
		'''Cumulative Distribution Function for a Gaussian normal distribution.
		If the input is gaussian normal, the output will be uniform in [0,1].'''
		return 0.5 * (1 + math.erf((x - mu) / invscale))
	return f


class NoisePass:
	def __init__(self, params):
		self._noise_params = {
			'octaves': params.get('octaves', 1),
			'persistence': params.get('persistence', 0.5),
			'lacunarity': params.get('lacunarity', 2.0)
		}
		self._scalex = params.get('scale_x', 1.0)
		self._scaley = params.get('scale_y', 1.0)
		self._convert = lambda x: x
		if params.get('distribution', None) == 'uniform':
			self._convert = gaussian_cdf(0.0, 0.4433703902714217)  # mean and standard deviation of the noise; this is experimentally determined
		self._hooks = []

	def add_hook(self, hook):
		self._hooks.append(hook)
		return hook

	async def generate(self, map):
		for x in range(map.width):
			for y in range(map.height):
				v = self._convert(noise.snoise2(x * self._scalex, y * self._scaley, **self._noise_params))
				for hook in self._hooks:
					await hook(map, (x, y), v)


class PlayerBasePass:
	def __init__(self):
		self._hooks = []

	def add_hook(self, hook):
		self._hooks.append(hook)
		return hook

	async def generate(self, map):
		for player in map.players:
			center_x = map.width / 2
			center_y = map.height / 2
			phi = 2 * math.pi / len(map.players)
			radius_x = center_x / math.sqrt(2)  # just so they don't end up right against the edge of the map
			radius_y = center_y / math.sqrt(2)
			for i, player in enumerate(map.players):
				base_x = int(center_x + radius_x * math.cos(phi * i))
				base_y = int(center_y + radius_y * math.sin(phi * i))
			for hook in self._hooks:
				await hook(map, player, (base_x, base_y))


class Generator:
	def __init__(self):
		self._passes = []

	def add_pass(self, pass_):
		self._passes.append(pass_)
		return pass_

	async def generate(self, players):
		width = height = int(math.sqrt(len(players) * MAP_AREA_PER_PLAYER) + 1)  # this gives each player roughly that much space
		print(f"Generating map with dimensions {width}x{height}")
		map = game.Map(players, width, height)
		await map.events.put(('MAP', map))
		for pass_ in self._passes:
			await pass_.generate(map)
		return map


def hook_terrain(terrain_type, min, max):
	async def hook(map, xy, v):
		if min <= v < max:
			await map.set_terrain(xy, terrain_type)
	return hook


def hook_resource(unit_type, min, max, tags):
	async def hook(map, xy, v):
		if min <= v < max:
			await map.create_unit(xy, unit_type, None)
	return hook


def hook_player_unit(unit_type, count=1):
	async def hook(map, player, xy):
		await map.create_unit(find_spot(map, xy, {"build"}), unit_type, player)
	return hook


def find_spot(map, xy, tags):
	for pos in game.vicinity(xy, map.width, map.height):
		cell = map[pos]
		if not tags <= cell.terrain_type.tags:
			continue
		return pos
	raise ValueError("No space to place unit")
