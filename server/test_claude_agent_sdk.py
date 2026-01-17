import asyncio
from claude_agent_sdk import ClaudeAgentOptions, query
async def main:
 options = ClaudeAgentOptions(
 system_prompt="你是一个资深的前端开发工程师，精通React和Vue框架，能够根据需求编写高质量的前端代码。",
 permission_mode="plan",
 cwd="/Users/zaneliu/Projects/open-source/friday-ai/web",
 )
 async for message in query(prompt="告诉我这是一个什么项目？", options=options):
 print(message)
asyncio.run(main)
