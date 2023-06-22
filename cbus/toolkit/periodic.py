import asyncio
import logging

class Periodic:
  """
  class that manages a queue of functions to be called while 
  leaving a interval between two successive calls 
  """
  def __init__(self, period=1):
    self.queue = asyncio.Queue()
    self.period = period
    loop = asyncio.get_event_loop()
    self.task = loop.create_task(self._work())

  async def _work(self):
    while True:
      try:
        action = await self.queue.get()  # async get
        action()
      except Exception as e:
        logging.error(f'Error executing task: {e}')
      finally:
        await asyncio.sleep(self.period)

  def enqueue(self, task):
    # task is a lambda or the name of a function with no argument
    self.queue.put_nowait(task)  # non-blocking put
