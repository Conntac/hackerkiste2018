import math
from heapdict import heapdict
from .game import vicinity


class PathFinder:
	"""
	Implement path finding using A*.
	"""

	def __init__(self, map):
		self.map = map

	def _idx(self, pos):
		x, y = pos
		return y * self.map.width + x

	def plan(self, start_pos, dest_pos):
		"""
		Search a path from start_pos to dest_pos.

		Returns a list of walkable positions forming a path from
		start_pos to dest_pos. Ignores whether any units are in the
		way. If no path to dest_pos can be found, returns a path to a
		nearby reachable position.
		"""

		map_size = self.map.width * self.map.height
		dist = [float('inf') for i in range(map_size)]
		prev = [None for i in range(map_size)]

		dist[self._idx(start_pos)] = 0

		pq = heapdict()
		for y in range(self.map.height):
			for x in range(self.map.width):
				pq[x, y] = dist[self._idx((x, y))]

		while pq:
			pos, _ = pq.popitem()
			x, y = pos

			for nx, ny in self._neighbors(x, y):
				new_dist = dist[self._idx(pos)] + 1
				if new_dist < dist[self._idx((nx, ny))]:
					dist[self._idx((nx, ny))] = new_dist
					# Heuristic function is only admissible if it never
					# overestimates true costs. Because diagonals only
					# have costs of 1, we cannot use the euclidian
					# distance as heuristic. Instead, we use the chebyshev
					# distance.
					pq[nx, ny] = new_dist + chebyshev_distance((nx, ny), dest_pos)
					prev[self._idx((nx, ny))] = x, y

		if math.isinf(dist[self._idx(dest_pos)]):
			for point in vicinity(dest_pos, self.map.width, self.map.height):
				if not math.isinf(dist[self._idx(point)]):
					dest_pos = point
					break
			else:
				raise ValueError("cannot find a path")

		return self._reconstruct_path(start_pos, dest_pos, prev)

	def _neighbors(self, x, y):
		offsets = [
			(-1, -1), (-1, 0), (-1, 1),
			(0, -1), (0, 1),
			(1, -1), (1, 0), (1, 1)
		]
		for x_offs, y_offs in offsets:
			nx = x + x_offs
			ny = y + y_offs
			if nx < 0 or ny < 0 or nx >= self.map.width or ny >= self.map.height:
				continue
			if 'walk' not in self.map[nx, ny].terrain_type.tags:
				continue
			unit = self.map[nx, ny].unit
			if unit is not None and ('resource' in unit.unit_type.tags or 'building' in unit.unit_type.tags):
			    continue
			yield (nx, ny)

	def _reconstruct_path(self, start_pos, dest_pos, prev):
		next_pos = dest_pos
		path = []
		while next_pos != start_pos:
			path.append(next_pos)
			next_pos = prev[self._idx(next_pos)]
		path.reverse()
		return path


def chebyshev_distance(a, b):
	"""Compute the chebyshev distance, or maximum metric, between a and b."""
	ax, ay = a
	bx, by = b
	return max(abs(ax - bx), abs(ay - by))
