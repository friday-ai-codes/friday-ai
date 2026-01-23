"""WebSocket consumers for workflows app."""
import json
from channels.generic.websocket import AsyncWebsocketConsumer
class WorkflowExecutionConsumer(AsyncWebsocketConsumer):
 """Consumer for workflow execution updates.
 Clients connect to: /ws/workflow-executions/{execution_id}/
 """
 async def connect(self):
 self.execution_id = self.scope["url_route"]["kwargs"]["execution_id"]
 self.group_name = f"execution_{self.execution_id}"
 # Join execution group
 await self.channel_layer.group_add(self.group_name, self.channel_name)
 await self.accept
 async def disconnect(self, close_code):
 # Leave execution group
 await self.channel_layer.group_discard(self.group_name, self.channel_name)
 async def receive(self, text_data):
 """Handle incoming messages from client (optional)."""
 pass
 async def workflow_event(self, event):
 """Handle workflow event message from group."""
 # Send message to WebSocket
 await self.send(text_data=json.dumps(event))
