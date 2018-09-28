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
