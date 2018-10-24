"""
:class:`~gymwipe.devices.core.Device` implementations for network devices
"""
from typing import Any, Tuple

from gymwipe.devices import Device
from gymwipe.envs.core import Interpreter
from gymwipe.networking.messages import (Packet, Signal, SimpleTransportHeader,
                                         StackSignals, Transmittable)
from gymwipe.networking.physical import Channel
from gymwipe.networking.stack import SimpleMac, SimplePhy, SimpleRrmMac
from gymwipe.simtools import Notifier, SimMan


class NetworkDevice(Device):
    """
    A subclass of :class:`~gymwipe.devices.core.Device` that extends the
    constructor's parameter list by a channel argument. The provided
    :class:`~gymwipe.networking.physical.Channel` object will be stored in the
    :attr:`channel` attribute.
    """

    def __init__(self, name: str, xPos: float, yPos: float, channel: Channel):
        """
        Args:
            name: The device name
            xPos: The device's physical x position
            yPos: The device's physical y position
            channel: The :class:`~gymwipe.networking.physical.Channel` instance
                that will be used for transmissions
        """
        super(NetworkDevice, self).__init__(name, xPos, yPos)

        self.channel: Channel = channel
        """
        :class:`~gymwipe.networking.physical.Channel`: The
            :class:`~gymwipe.networking.physical.Channel` instance that
            is used for transmissions
        """

class SimpleNetworkDevice(NetworkDevice):
    """
    A :class:`NetworkDevice` implementation running a network stack that
    consists of a SimplePHY and a SimpleMAC. It offers a method for sending a
    packet using the MAC layer, as well as a callback method that will be
    invoked when a packet is received. Also, receiving can be turned on or of by
    setting :attr:`receive` either to ``True`` or to ``False``.
    """

    def __init__(self, name: str, xPos: float, yPos: float, channel: Channel):
        super(SimpleNetworkDevice, self).__init__(name, xPos, yPos, channel)
        self._receiving = False
        self._receiverProcess = None # a SimPy receiver process

        self.mac: bytes = SimpleMac.newMacAddress()
        """bytes: The address that is used by the MAC layer to identify this device"""

        # Initialize PHY and MAC
        self._phy = SimplePhy("phy", self, self.channel)
        self._mac = SimpleMac("mac", self, self.mac)
        # Connect them with each other
        self._mac.gates["phy"].biConnectWith(self._phy.gates["mac"])
    
    # inherit __init__ docstring
    __init__.__doc__ = NetworkDevice.__init__.__doc__
    
    RECEIVE_TIMEOUT = 100
    """
    int: The timeout in seconds for the simulated blocking MAC layer receive call
    """
    
    @property
    def receiving(self) -> bool:
        return self._receiving
    
    @receiving.setter
    def receiving(self, receiving: bool):
        if receiving != self._receiving:
            if receiving:
                # start receiving
                if self._receiverProcess is None:
                    self._receiverProcess = SimMan.process(self._receiver())
            self._receiving = receiving

    def send(self, data: Transmittable, destinationMacAddr: bytes):
        p = Packet(SimpleTransportHeader(self.mac, destinationMacAddr), data)
        self._mac.gates["transport"].send(p)

    def _receiver(self):
        # A blocking receive loop
        while self._receiving:
            receiveCmd = Signal(StackSignals.RECEIVE, {"duration": self.RECEIVE_TIMEOUT})
            self._mac.gates["transport"].send(receiveCmd)
            result = yield receiveCmd.eProcessed
            if result:
                self.onReceive(result)
        # Reset receiver process reference so one can now that the process has
        # terminated
        self._receiverProcess = None

    def onReceive(self, packet: Packet):
        """
        This method is invoked whenever :attr:`receiving` is ``True`` and a
        packet has been received.

        Note:
            After :attr:`receiving` has been set to ``False`` it might still be
            called within :attr:`RECEIVE_TIMEOUT` seconds.

        Args:
            packet: The packet that has been received
        """

class SimpleRrmDevice(NetworkDevice):
    """
    A Radio Resource Management :class:`NetworkDevice` implementation. It runs a
    network stack consisting of a SimplePHY and a SimpleRrmMAC. It offers a
    method for channel assignment and operates an
    :class:`~gymwipe.envs.core.Interpreter` instance that provides observations
    and rewards for a learning agent.
    """

    def __init__(self, name: str, xPos: float, yPos: float, channel: Channel, interpreter: Interpreter):
        """
            interpreter: The :class:`~gymwipe.envs.core.Interpreter` instance to
                be used for observation and reward calculations
        """
        super(SimpleRrmDevice, self).__init__(name, xPos, yPos, channel)
        self._interpreter = interpreter

        # Initialize PHY and MAC
        self._phy = SimplePhy("phy", self, self.channel)
        self._mac = SimpleRrmMac("mac", self)
        # Connect them with each other
        self._mac.gates["phy"].biConnectWith(self._phy.gates["mac"])
    
    # merge __init__ docstrings
    __init__.__doc__ = NetworkDevice.__init__.__doc__ + __init__.__doc__
    
    @property
    def mac(self) -> bytes:
        """bytes: The RRM's MAC address"""
        return self._mac.addr

    @property
    def packetReceivedNotifier(self) -> Notifier:
        """
        A :class:`~gymwipe.simtools.Notifier` that is triggered when the RRM
        receives a packet that is not addressed to it.
        """
        return self._mac.gates["transport"].output.nReceives

    def assignChannel(self, deviceMac: bytes, duration: int) -> Tuple[Any, float]:
        """
        Makes the RRM assign the channel to a certain device for a certain time.

        Args:
            deviceMac: The MAC address of the device to assign the channel to
            duration: The number of time units for the channel to be assigned to
                the device
        
        Returns:
            The :class:`~gymwipe.networking.messages.Signal` object that was
            used to make the RRM MAC layer assign the channel. Once the channel
            assignment is over, the signal's
            :attr:`~gymwipe.networking.messages.Signal.eProcessed` event will
            succeed.
        """
        assignSignal = Signal(
            StackSignals.ASSIGN,
            {"duration": duration, "dest": deviceMac}
        )
        self._interpreter.onChannelAssignment(duration, deviceMac)
        self._mac.gates["transport"].send(assignSignal)

        return assignSignal

    def getFeedback(self) -> Tuple[Any, float, bool]:
        """
        Call this at the end of a channel assignment to get an observation, a
        reward. and a done flag from the
        :class:`~gymwipe.envs.core.Interpreter`.

        Returns:
            A tuple consisting of the observation, the reward, and the done flag
            handed out by the :class:`~gymwipe.envs.core.Interpreter`
        """
        observation = self._interpreter.getObservation()
        reward = self._interpreter.getReward()
        done = self._interpreter.getDone()
        return observation, reward, done
