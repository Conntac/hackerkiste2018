import curio


def clamp(v, min_, max_):
	return min(max(min_, v), max_)


class IdPool:
	'''Manages a set of IDs. Use create to obtain a new unique id, and use destroy when you no longer need it.'''
	def __init__(self, first_id=1):  # this leaves 0 for special cases, e.g. as a NIL value
		self._next_id = first_id
		self._recycle = set()  # destroyed IDs that can be reused

	def create(self):
		if self._recycle:
			return self._recycle.pop()
		else:
			id_ = self._next_id
			self._next_id += 1
			return id_

	def destroy(self, id_):
		self._recycle.add(id_)
		while self._next_id - 1 in self._recycle:
			self._recycle.discard(self._next_id - 1)
			self._next_id -= 1


class IdList:
	def __init__(self, typ, first_id=1):  # This leaves 0 free, in case a NIL value is needed
		self._ids = IdPool(first_id)
		self._typ = typ
		self._items = {}

	def create(self, *args, **kwargs):
		item = self._typ(self._ids.create(), *args, **kwargs)
		self._items[item.id] = item
		return item

	def create_type(self, typ, *args, **kwargs):
		if not issubclass(typ, self._typ):
			raise TypeError()
		item = typ(self._ids.create(), *args, **kwargs)
		self._items[item.id] = item
		return item

	def get(self, id):
		return self._items[id]

	def destroy(self, item_or_id):
		id_ = item_or_id.id if isinstance(item_or_id, self._typ) else int(item_or_id)
		del self._items[id_]
		self._ids.destroy(id_)

	def __iter__(self):
		yield from self._items.values()

	def __len__(self):
		return len(self._items)

	def resolve(self, item):
		if isinstance(item, int):
			return self._items[item]
		elif self._items[item.id] == item:
			return item
		else:
			raise ValueError("Unknown IdList Item")


class Signal:
	def __init__(self, *params, **kwparams):
		self.handlers = set()
		self.params = params
		self.kwparams = kwparams

	def attach(self, handler):
		self.handlers.add(handler)

	def __iadd__(self, handler):
		self.handlers.add(handler)

	def detach(self, handler):
		self.handlers.discard(handler)

	def __call__(self, *args, **kwargs):
		for a, p in zip(args, self.params):
			if not isinstance(a, p):
				raise TypeError("Signal argument type mismatch")
		for (n, a) in kwargs.items():
			if n not in self.kwparams or not isinstance(a, self.kwparams[n]):
				raise TypeError("Signal keyword argument type mismatch")
		for handler in self.handlers:
			handler(*args, **kwargs)


class ScopeTask:
	def __init__(self, coro):
		self.coro = coro
		self.task = None
	
	async def __aenter__(self):
		self.task = await curio.spawn(self.coro)

	async def __aexit__(self, *args):
		await self.task.cancel()
		self.task = None

