all: reset/proto/types_pb2.py reset/proto/commands_pb2.py reset/proto/events_pb2.py

reset/proto/%_pb2.py: reset/proto/%.proto
	protoc -Ireset/proto --python_out=reset/proto $^
	sed -i 's/^import \(.*\)_pb2/from reset.proto import \1_pb2/' $@
	sed -i 's/^import \(.*\)_pb2 as \1__pb2/from reset.proto import \1_pb2 as \1__pb2/' $@
