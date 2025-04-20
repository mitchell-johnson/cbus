# https://github.com/eclipse/paho.mqtt.python/blob/master/examples/loop_asyncio.py
import asyncio
import logging
import paho.mqtt.client as mqtt


logger = logging.getLogger(__name__)


class AsyncioHelper:
    def __init__(self, loop, client):
        self.loop = loop
        self.client = client
        self.client.on_socket_open = self.on_socket_open
        self.client.on_socket_close = self.on_socket_close
        self.client.on_socket_register_write = self.on_socket_register_write
        self.client.on_socket_unregister_write = self.on_socket_unregister_write
        self.misc = None
        self._closed = False
        self._sock = None

    def on_socket_open(self, client, userdata, sock):
        self._sock = sock
        self.loop.add_reader(sock, client.loop_read)
        self.misc = self.loop.create_task(self.misc_loop())

    def on_socket_close(self, client, userdata, sock):
        if self._sock:
            try:
                self.loop.remove_reader(sock)
            except Exception as e:
                logger.error(f"Error removing reader: {e}")
        
        self._sock = None
        self.cleanup_misc_task()

    def on_socket_register_write(self, client, userdata, sock):
        try:
            self.loop.add_writer(sock, client.loop_write)
        except Exception as e:
            logger.error(f"Error adding writer: {e}")

    def on_socket_unregister_write(self, client, userdata, sock):
        try:
            self.loop.remove_writer(sock)
        except Exception as e:
            logger.error(f"Error removing writer: {e}")

    async def misc_loop(self):
        while not self._closed and self.client.loop_misc() == mqtt.MQTT_ERR_SUCCESS:
            try:
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                logger.debug("Misc loop cancelled")
                break
    
    def cleanup_misc_task(self):
        """Clean up the misc task."""
        if self.misc and not self.misc.done():
            self.misc.cancel()
    
    def cleanup(self):
        """Clean up all resources."""
        if self._closed:
            return
        
        self._closed = True
        self.cleanup_misc_task()
        
        # Clean up socket readers/writers
        if self._sock:
            try:
                self.loop.remove_reader(self._sock)
                self.loop.remove_writer(self._sock)
            except Exception as e:
                logger.error(f"Error cleaning up socket: {e}")
            
            self._sock = None
        
        # Remove circular references
        if self.client:
            self.client.on_socket_open = None
            self.client.on_socket_close = None
            self.client.on_socket_register_write = None
            self.client.on_socket_unregister_write = None
        
        logger.debug("AsyncioHelper resources cleaned up")
