# RESET
Real-Time Strategy Game Framework

## Running
You need the requirements listed in `requirements.txt`, e.g.

```
pip3 install -r requirements.txt
```

You must also compile the protocol buffers, which are required for network communication.

```
make
```

You can run the server by:

```
python -m reset.server
```

And the client using

```
python -m reset.client
```

#### Known issues

If you're on Ubuntu and `make` returns something like 
```
protoc -Ireset/proto --python_out=reset/proto reset/proto/types.proto
make: protoc: Command not found
Makefile:4: recipe for target 'reset/proto/types_pb2.py' failed
make: *** [reset/proto/types_pb2.py] Error 127
```

try installing the following package: 

`sudo apt-get install protobuf-compiler`
