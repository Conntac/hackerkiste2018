import curio
import google.protobuf.json_format


async def recv_len(socket, length):
	buf_back = bytearray(length)
	buf = memoryview(buf_back)
	have = 0
	while have < length:
		got = await socket.recv_into(buf[have:], length - have)
		if got == 0:
			raise ConnectionResetError("Client Disconnected")
		have += got
	return buf_back


class Protocol:
	def __init__(self):
		self._handlers = {f.command_type: getattr(self, n) for n, f in self.__class__.__dict__.items() if hasattr(f, 'command_type')}

	def get_handler(self, key):
		return self._handlers.get(key, self.on_unhandled)

	async def handle(self, server, client, message):
		return await self.get_handler(type(message))(server, client, message)

	async def on_connect(self, server, client):
		pass
	
	async def on_disconnect(self, server, client):
		pass

	async def on_unhandled(self, server, client, message):
		if hasattr(message, 'DESCRIPTOR'):
			print(message.DESCRIPTOR.name, google.protobuf.json_format.MessageToJson(message))
		else:
			print("Unhandled:", message)

	@staticmethod
	def handler(command_type):
		def wrapper(f):
			f.command_type = command_type
			return f
		return wrapper
