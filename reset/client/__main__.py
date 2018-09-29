#!/usr/bin/python3

import argparse
import shlex
import sys

import curio

from . import ProtocolUser, Client, Rules
from ..proto import commands_pb2 as commands, events_pb2 as events
from .. import util


async def command_join(pargs, client, args):
	await client.send(commands.CmdJoin(name=pargs.name))


async def command_start(pargs, client, args):
	await client.send(commands.CmdGameStart())


async def command_action(pargs, client, args):
	ap = argparse.ArgumentParser()
	ap.add_argument("action_type", type=int)
	ap.add_argument("unit", type=int)
	ap.add_argument("--target", "-t", type=int, default=None)
	ap.add_argument("-x", type=int, default=None)
	ap.add_argument("-y", type=int, default=None)
	args = ap.parse_args(args)
	cmd = commands.CmdActionQueue(action_type_id=args.action_type, unit_id=args.unit)
	if args.target is not None:
		cmd.target_unit_id = args.target
	if args.x is not None and args.y is not None:
		cmd.target_cell.x = args.x
		cmd.target_cell.y = args.y
	await client.send(cmd)


async def cli(pargs, rules, client):
	console = curio.io.FileStream(sys.stdin.buffer)
	while True:
		command = await console.readline()
		command = shlex.split(command.strip().decode())
		command, args = command[0], command[1:]
		if command == "exit":
			await handler_task.cancel()
			return
		cmd_handler = globals().get("command_" + command, None)
		if cmd_handler is None:
			print(f"Unknown command: {command}")
		else:
			try:
				await cmd_handler(pargs, client, args)
			except:
				traceback.print_exc()
	
async def main():
	ap = argparse.ArgumentParser()
	ap.add_argument("host")
	ap.add_argument("port", type=int)
	ap.add_argument("--join", action='store_true', default=False)
	ap.add_argument("--start", action='store_true', default=False)
	ap.add_argument("--name", default="Player")
	args = ap.parse_args()

	rules = Rules()
	protocol = ProtocolUser(rules)
	client = Client(args.host, args.port, protocol)
	async with util.ScopeTask(client.run()):
		cli_task = await curio.spawn(cli(args, rules, client))
		if args.join:
			await command_join(args, client, [])
		if args.start:
			await command_start(args, client, [])
		await cli_task.join()


if __name__ == '__main__':
	curio.run(main())

