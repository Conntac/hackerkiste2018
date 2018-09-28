import traceback

from wsproto.connection import ConnectionType, WSConnection
from wsproto.events import ConnectionClosed, ConnectionRequested, PingReceived, TextReceived
import curio
from curio import socket
import google.protobuf.json_format

from ..proto import events_pb2 as events, commands_pb2 as commands
from . import Client


class WebsocketClient(Client):
	def __init__(self, sock, addr):
		super(WebsocketClient, self).__init__()
		self.sock = sock
		self.addr = addr
		self._queue = curio.Queue()

	async def close(self):
		self.sock.shutdown(socket.SHUT_RDWR)
		self.sock.close()
		await super(WebsocketClient, self).close()

	async def _run_recv(self, server, ws):
		await server.protocol.on_connect(server, self)
		try:
			while True:
				segment = await self.sock.recv(0xffff)
				#print(">", self, segment)
				ws.receive_bytes(segment)
				for event in ws.events():
					if isinstance(event, ConnectionRequested):
						print('Accepting WebSocket upgrade')
						ws.accept(event)
					elif isinstance(event, ConnectionClosed):
						print('Connection closed: code={}/{} reason={}'.format(
							event.code.value, event.code.name, event.reason))
						raise ConnectionResetError()
					elif isinstance(event, TextReceived):
						try:
							wrapper = commands.ClientToServer()
							google.protobuf.json_format.Parse(event.data, wrapper)
							message = getattr(wrapper, wrapper.WhichOneof("payload"))
							await server.protocol.handle(server, self, message)
						except:
							traceback.print_exc()
					elif isinstance(event, PingReceived):
						pass
					else:
						print('Unknown event: {!r}'.format(event))
				await self.sock.sendall(ws.bytes_to_send())
		except ConnectionResetError:
			await server.protocol.on_disconnect(server, self)

	async def _run_send(self, ws):
		while True:
			message = await self._queue.get()
			wrapper = events.ServerToClient()
			for fd in wrapper.DESCRIPTOR.oneofs_by_name["payload"].fields:
				if message.DESCRIPTOR == fd.message_type:
					getattr(wrapper, fd.name).CopyFrom(message)
					break
			packet = google.protobuf.json_format.MessageToJson(wrapper)
			ws.send_data(packet)
			#print("<", self, packet)
			await self.sock.sendall(ws.bytes_to_send())

	async def run(self, server):
		self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
		ws = WSConnection(ConnectionType.SERVER)
		async with curio.TaskGroup() as g:
			await g.spawn(self._run_recv(server, ws))
			await g.spawn(self._run_send(ws))

	async def send(self, message):
		await self._queue.put(message)

	def __str__(self):
		return f"WebsocketClient{{{self.addr[0]}:{self.addr[1]}}}"


async def ws_server(server, host, port):
	async def ws_client(sock, addr):
		client = WebsocketClient(sock, addr)
		await server.add_client(client)
		try:
			await client.run(server)
		finally:
			await server.remove_client(client)
	print(f"Websocket Server listening on {host}:{port}")
	await curio.tcp_server(host, port, ws_client)