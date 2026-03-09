"""子步骤状态变更 signal。
emit_sub_step 发送此 signal，handler 负责 WebSocket 广播，
实现节点代码与通信层的解耦。
"""
import django.dispatch
# 参数: sender (node class), sub_step (NodeSubStep), node_execution_id (UUID)
sub_step_updated = django.dispatch.Signal
