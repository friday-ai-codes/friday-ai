"""WebSocket integration tests."""
import pytest
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from friday.asgi import application
User = get_user_model
@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_workflow_execution_consumer(settings):
 """Test WebSocket connection and message receiving."""
 # Use InMemoryChannelLayer for testing
 settings.CHANNEL_LAYERS = {
 "default": {
 "BACKEND": "channels.layers.InMemoryChannelLayer",
 },
 }
 # Test connection to a path
 execution_id = "00000000-0000-0000-0000-000000000000"
 communicator = WebsocketCommunicator(
 application,
 f"/ws/workflow-executions/{execution_id}/"
 )
 connected, subprotocol = await communicator.connect
 assert connected
 # Test sending group message
 from channels.layers import get_channel_layer
 channel_layer = get_channel_layer
 message = {
 "type": "workflow.event",
 "event": "execution_started",
 "execution_id": execution_id,
 "status": "running"
 }
 await channel_layer.group_send(f"execution_{execution_id}", message)
 # Receive message
 response = await communicator.receive_json_from
 assert response == message
 await communicator.disconnect
