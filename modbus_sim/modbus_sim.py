from pymodbus.server import StartTcpServer
from pymodbus.datastore import (
    ModbusSequentialDataBlock,
    ModbusServerContext,
    ModbusSlaveContext,
)

store = ModbusSlaveContext(
    hr=ModbusSequentialDataBlock(0, [2040] * 10)
)
context = ModbusServerContext(slaves=store, single=True)

print("Fake sensor running on localhost:502 ...")
StartTcpServer(context=context, address=("localhost", 502))
