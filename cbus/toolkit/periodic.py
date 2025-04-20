import asyncio
import logging

class Periodic:
  """
  class that manages a queue of functions to be called while 
  leaving a interval between two successive calls 
  """
  def __init__(self, period=1, max_queue_size=1000):
    self.queue = asyncio.Queue(maxsize=max_queue_size)
    self.period = period
    self.running = True
    loop = asyncio.get_event_loop()
    self.task = loop.create_task(self._work())

  async def _work(self):
    while self.running:
      try:
        action = await self.queue.get()  # async get
        action()
        self.queue.task_done()  # Mark task as done to track completion
      except asyncio.CancelledError:
        break
      except Exception as e:
        logging.error(f'Error executing task: {e}')
      finally:
        await asyncio.sleep(self.period)

  def enqueue(self, task):
    # task is a lambda or the name of a function with no argument
    if self.running and not self.queue.full():
      self.queue.put_nowait(task)  # non-blocking put
    else:
      logging.warning("Queue full or shutting down, task not added")
  
  async def cleanup(self):
    """Properly clean up the periodic task."""
    self.running = False
    if self.task and not self.task.done():
      self.task.cancel()
      try:
        await self.task
      except asyncio.CancelledError:
        pass  # Expected during cancellation
    
    # Process remaining items in the queue if needed
    if not self.queue.empty():
      logging.warning(f"Discarding {self.queue.qsize()} pending tasks during cleanup")
      # Clear the queue
      while not self.queue.empty():
        try:
          self.queue.get_nowait()
          self.queue.task_done()
        except asyncio.QueueEmpty:
          break
