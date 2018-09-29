import shlex
import logging
from functools import reduce

import curio
import termbox


def clamp(x, mn, mx):
	return max(mn, min(x, mx))


def procrustes(s, l):
	return s[:l] + ' ' * (l - len(s))


class TermboxAsync:
	def __init__(self):
		self.tb = None
		self._group = curio.TaskGroup()
		self._queue = curio.Queue()

	async def _watch(self, fd):
		while True:
			await curio.traps._read_wait(fd)
			event = self.tb.poll_event()
			await self._queue.put(event)

	def __getattr__(self, name):
		return getattr(self.tb, name)

	async def __aenter__(self):
		self.tb = termbox.Termbox()
		for fd in self.tb.poll_fds():
			await self._group.spawn(self._watch(fd))
		return self

	async def __aiter__(self):
		while True:
			yield await self._queue.get()

	async def __aexit__(self, *args):
		await self._group.cancel_remaining()

	def write(self, x, y, text, *, length=None, fill=None, fg=termbox.WHITE, bg=termbox.BLACK):
		for i, c in enumerate(text[:length]):
			self.change_cell(x + i, y, ord(c), fg, bg)
		if fill:
			for i in range(i, length):
				self.change_cell(x + i, y, ord(fill), fg, bg)


class LineEditWidget:
	def __init__(self):
		self.cursor = 0
		self.text = ""
		self.on_submit = None
		self.fg = termbox.BLACK
		self.bg = termbox.WHITE
		self.prefix = "> "
		self.suffix = None

	async def on_key(self, tb, key, ch, mod):
		line_change = False
		# nav keys
		if key == termbox.KEY_HOME:
			self.cursor = 0
		elif key == termbox.KEY_END:
			self.cursor = len(self.text)
		elif key == termbox.KEY_ARROW_LEFT:
			self.cursor -= 1
		elif key == termbox.KEY_ARROW_RIGHT:
			self.cursor += 1
		# edit keys
		elif key == termbox.KEY_BACKSPACE or key == termbox.KEY_BACKSPACE2:
			line_change = self.cursor != 0
			self.text = self.text[:max(0, self.cursor - 1)] + self.text[self.cursor:]
			self.cursor -= 1
		elif key == termbox.KEY_DELETE:
			line_change = self.cursor != len(self.text)
			self.text = self.text[:self.cursor] + self.text[self.cursor + 1:]
		elif key == termbox.KEY_CTRL_U:
			line_change = self.text != ""
			self.text = ""
			self.cursor = 0
		elif key == termbox.KEY_SPACE:
			self.text = self.text[:self.cursor] + ' ' + self.text[self.cursor:]
			self.cursor += 1
			line_change = True
		elif key == termbox.KEY_ENTER:
			if self.on_submit is not None:
				await self.on_submit(self.text)
			self.text = ""
			self.cursor = 0
			line_change = True
		elif ch is not None:
			self.text = self.text[:self.cursor] + ch + self.text[self.cursor:]
			self.cursor += 1
			line_change = True
		else:
			return False

		self.cursor = clamp(self.cursor, 0, len(self.text))
		return True

	async def render(self, tb, x, y, w, h):
		prefix = self.prefix or ""
		suffix = self.suffix or ""
		content_length = w - len(prefix) - len(suffix)
		tb.write(x, y, prefix + procrustes(self.text, content_length) + suffix, fg=self.fg, bg=self.bg)


class Screen:
	async def on_key(self, tb, key, ch, mod):
		pass

	async def render(self, tb, x, y, w, h):
		pass


class ScreenLog:
	def __init__(self):
		self.lines = []
		self.cursor = 0

	def append_message(self, message):
		self.lines.extend(message.split('\n'))

	async def render(self, tb, x, y, w, h):
		for i, line in enumerate(self.lines[self.cursor:self.cursor+h]):
			tb.write(x, y + i, line[:w])

	async def on_key(self, tb, key, ch, mod):
		if key == termbox.KEY_PGUP:
			self.cursor = max(self.cursor - 20, 0)
		elif key == termbox.KEY_PGDN:
			self.cursor = min(self.cursor + 20, len(self.lines))
		elif key == termbox.KEY_ARROW_UP:
			self.cursor = max(self.cursor - 1, 0)
		elif key == termbox.KEY_ARROW_DOWN:
			self.cursor = min(self.cursor + 1, len(self.lines))
		else:
			return False
		return True


class ScreenMap:
	# (char, background, foreground)
	DEFAULT = (" ", termbox.DEFAULT, termbox.DEFAULT)
	TERRAIN_TYPES = {
		"grass": (" ", termbox.GREEN, termbox.BLACK),
		"mountain": ("M", termbox.YELLOW, termbox.BLACK),
		"water": (" ", termbox.BLUE, termbox.WHITE),
	}
	TERRAIN_TYPE_DEFAULT = (" ", termbox.WHITE, termbox.BLACK)
	UNIT_TYPES = {
		"city": ("X", None, termbox.WHITE),
		"citizen": (".", None, termbox.BLACK|termbox.BOLD),
	}
	UNIT_TYPE_DEFAULT = ("?", termbox.WHITE, termbox.BLACK)
	PLAYERS = {
		1: (None, None, termbox.RED),
		2: (None, None, termbox.BLUE),
	}
	PLAYER_DEFAULT = (None, None, termbox.WHITE)
	def __init__(self, client):
		self.client = client

	def _resolve(self, profiles):
		return (reduce(lambda a, b: b[0] if b[0] is not None else a, profiles, ScreenMap.DEFAULT[0]),
			reduce(lambda a, b: b[1] if b[1] is not None else a, profiles, ScreenMap.DEFAULT[1]),
			reduce(lambda a, b: b[2] if b[2] is not None else a, profiles, ScreenMap.DEFAULT[2]))

	async def render(self, tb, x, y, w, h):
		if self.client.map is not None:
			for my in range(min(self.client.map.height, h)):
				for mx in range(min(self.client.map.width, w)):
					c = self.client.map[mx, my]
					cell_profiles = [
						ScreenMap.DEFAULT,
						ScreenMap.TERRAIN_TYPES.get(c.terrain_type.name, ScreenMap.TERRAIN_TYPE_DEFAULT)]
					if c.unit is not None:
						cell_profiles.append(ScreenMap.UNIT_TYPES.get(c.unit.unit_type.name, ScreenMap.UNIT_TYPE_DEFAULT))
						cell_profiles.append(ScreenMap.PLAYERS.get(c.unit.player_id, ScreenMap.PLAYER_DEFAULT))
					ch, bg, fg = self._resolve(cell_profiles)
					tb.change_cell(x + mx, y + my, ord(ch), fg, bg)


class UiLoggingHandler(logging.Handler):
	def __init__(self, screen):
		super(UiLoggingHandler, self).__init__()
		self.screen = screen

	def emit(self, record):
		self.screen.append_message(self.format(record))


class Ui:
	def __init__(self, client):
		self.client = client
		self.line = LineEditWidget()
		self.line.on_submit = self._line_submit
		self.screens = [ScreenLog(), ScreenMap(client)]
		self.screen_active = 0
		logging.getLogger().addHandler(UiLoggingHandler(self.screens[0]))

	@property
	def screen(self):
		return self.screens[self.screen_active]

	async def _line_submit(self, text):
		parts = shlex.split(text)
		self.screen_active = 0
		await self.client.run_command(parts[0], parts[1:])

	async def render(self, tb, x, y, w, h):
		if self.screen is not None:
			await self.screen.render(tb, x, y, w, h - 1)
		await self.line.render(tb, 0, h - 1, w, 1)

	async def on_key(self, tb, key, ch, mod):
		if key == termbox.KEY_TAB:
			self.screen_active = (self.screen_active + 1) % len(self.screens)
			return True
		if await self.line.on_key(tb, key, ch, mod):
			return True
		if await self.screen.on_key(tb, key, ch, mod):
			return True

