import traceback

import curio

from ..proto import events_pb2 as events, commands_pb2 as commands, recv_len
from . import Client


class TcpClient(Client):
	def __init__(self, sock, addr):
		super(TcpClient, self).__init__()
		self.sock = sock
		self.addr = addr
		self._queue = curio.Queue()  # binary packets

	async def close(self):
		self.sock.shutdown(socket.SHUT_RDWR)
		self.sock.close()
		await super(TcpClient, self).close()

	async def _run_recv(self, server):
		await server.protocol.on_connect(server, self)
		try:
			while True:
				packet_length = int.from_bytes(await recv_len(self.sock, 4), 'big')
				packet = await recv_len(self.sock, packet_length)
				try:
					wrapper = commands.ClientToServer()
					wrapper.ParseFromString(packet)
					message = getattr(wrapper, wrapper.WhichOneof("payload"))
					await server.protocol.handle(server, self, message)
				except:
					traceback.print_exc()
		except ConnectionResetError:
			await server.protocol.on_disconnect(server, self)

	async def _run_send(self):
		while True:
			message = await self._queue.get()
			wrapper = events.ServerToClient()
			for fd in wrapper.DESCRIPTOR.oneofs_by_name["payload"].fields:
				if message.DESCRIPTOR == fd.message_type:
					getattr(wrapper, fd.name).CopyFrom(message)
					break
			packet = wrapper.SerializeToString()
			#print(self, "<", packet)
			await self.sock.sendall(len(packet).to_bytes(4, 'big'))
			await self.sock.sendall(packet)

	async def run(self, server):
		async with curio.TaskGroup() as g:
			await g.spawn(self._run_recv(server))
			await g.spawn(self._run_send())

	async def send(self, message):
		await self._queue.put(message)

	def __str__(self):
		return f"TcpClient{{{self._addr[0]}:{self._addr[1]}}}"


async def tcp_server(server, host, port):
	async def tcp_client(sock, addr):
		client = TcpClient(sock, addr)
		await server.add_client(client)
		try:
			await client.run(server)
		finally:
			await server.remove_client(client)
	print(f"TCP Server listening on {host}:{port}")
	await curio.tcp_server(host, port, tcp_client)
