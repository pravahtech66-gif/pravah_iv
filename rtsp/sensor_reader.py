from pymodbus.client import ModbusSerialClient, ModbusTcpClient
from pymodbus.exceptions import ModbusException
import serial.tools.list_ports


def read_sensor_once(sensor_config: dict) -> tuple:
    protocol = sensor_config.get("protocol", "")

    if protocol == "modbus_rtu":
        client = ModbusSerialClient(
            port=sensor_config["com_port"],
            baudrate=sensor_config["baud_rate"],
            parity=sensor_config.get("parity", "N"),
            stopbits=1,
            bytesize=8,
            timeout=2,
        )
    elif protocol == "modbus_tcp":
        client = ModbusTcpClient(
            host=sensor_config["tcp_host"],
            port=sensor_config.get("tcp_port", 502),
        )
    else:
        raise RuntimeError(f"Unknown protocol: {protocol!r}")

    try:
        if not client.connect():
            raise RuntimeError(f"Could not connect ({protocol})")

        slave_id = sensor_config.get("slave_id", 1)
        register = sensor_config["address"]

        if sensor_config.get("register_type", "holding") == "holding":
            result = client.read_holding_registers(register, count=1, device_id=slave_id)
        else:
            result = client.read_input_registers(register, count=1, device_id=slave_id)

        if result.isError():
            raise RuntimeError(f"Register read error: {result}")

        raw = result.registers[0]
        distance = raw * sensor_config["scale_factor"]

        unit = sensor_config.get("unit", "m")
        if unit == "cm":
            distance_m = distance / 100.0
        elif unit == "mm":
            distance_m = distance / 1000.0
        else:
            distance_m = float(distance)

        return float(distance_m), raw

    except ModbusException as e:
        raise RuntimeError(f"{protocol} ModbusException: {e}")
    finally:
        client.close()


def list_com_ports() -> list:
    try:
        return [
            {"port": p.device, "description": p.description}
            for p in serial.tools.list_ports.comports()
        ]
    except Exception:
        return []
