#!/usr/bin/env python
"""Qdrant 向量召回测试脚本
使用方法:
 cd server
 python scripts/test_qdrant_search.py --repo-id <repository_id> --query "你的查询"
示例:
 python scripts/test_qdrant_search.py --repo-id 48338acf-35d3-4b44-abf --query "用户认证逻辑"
 python scripts/test_qdrant_search.py --repo-id 48338acf-35d3-4b44-abf --query "如何处理错误" --top-k 10
 python scripts/test_qdrant_search.py --list-collections
 python scripts/test_qdrant_search.py --repo-id 48338acf-35d3-4b44-abf --stats
"""
import argparse
import asyncio
import os
import sys
# 设置 Django 环境
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "friday.settings")
import django
django.setup
from services.embedding import EmbeddingService # noqa: E402
from services.qdrant_service import QdrantService # noqa: E402
async def generate_embedding_manual(
 text: str, api_url: str, model: str, api_key: str | None = None
) -> list[float] | None:
 """使用手动指定的配置生成 embedding"""
 import httpx
 try:
 async with httpx.AsyncClient(timeout=60.0) as client:
 headers = {"Content-Type": "application/json"}
 if api_key:
 headers["Authorization"] = f"Bearer {api_key}"
 # 检查是否是 Ollama API
 if "/api/embeddings" in api_url:
 request_body = {"model": model, "prompt": text}
 else:
 request_body = {"model": model, "input": text}
 response = await client.post(api_url, json=request_body, headers=headers)
 response.raise_for_status
 data = response.json
 if "data" in data and len(data["data"]) > 0:
 return data["data"][0]["embedding"]
 elif "embedding" in data:
 return data["embedding"]
 elif "embeddings" in data and len(data["embeddings"]) > 0:
 return data["embeddings"][0]
 else:
 print(f" ❌ 未知的响应格式: {data}")
 return None
 except Exception as e:
 print(f" ❌ Embedding API 错误: {e}")
 return None
def print_separator(char: str = "-", length: int = 60) -> None:
 print(char * length)
def list_collections -> None:
 """列出所有 Qdrant 集合"""
 print("\n📦 Qdrant 集合列表:")
 print_separator
 try:
 client = QdrantService.get_client
 collections = client.get_collections
 if not collections.collections:
 print(" (没有找到任何集合)")
 return
 for col in collections.collections:
 info = client.get_collection(col.name)
 points_count = info.points_count
 vector_size = info.config.params.vectors.size # type: ignore[union-attr]
 print(f" • {col.name}")
 print(f" 向量数量: {points_count}, 维度: {vector_size}")
 except Exception as e:
 print(f" ❌ 错误: {e}")
def show_collection_stats(repository_id: str) -> None:
 """显示集合统计信息"""
 collection_name = QdrantService.get_collection_name(repository_id)
 print(f"\n📊 集合统计: {collection_name}")
 print_separator
 try:
 client = QdrantService.get_client
 info = client.get_collection(collection_name)
 print(f" 向量总数: {info.points_count}")
 print(f" 向量维度: {info.config.params.vectors.size}") # type: ignore[union-attr]
 print(f" 距离度量: {info.config.params.vectors.distance}") # type: ignore[union-attr]
 # 获取文件统计
 file_hashes = QdrantService.get_stored_file_hashes(repository_id)
 print(f" 索引文件数: {len(file_hashes)}")
 if file_hashes:
 print("\n 📁 已索引文件 (前 20 个):")
 for i, file_path in enumerate(list(file_hashes.keys)[:20]):
 print(f" {i + 1}. {file_path}")
 if len(file_hashes) > 20:
 print(f" ... 还有 {len(file_hashes) - 20} 个文件")
 except Exception as e:
 print(f" ❌ 错误: {e}")
async def search_qdrant(
 repository_id: str,
 query: str,
 top_k: int = 5,
 language: str | None = None,
 embedding_url: str | None = None,
 embedding_model: str = "BAAI/bge-m3",
 embedding_key: str | None = None,
 embedding_dim: int | None = None,
) -> None:
 """执行向量搜索"""
 collection_name = QdrantService.get_collection_name(repository_id)
 print("\n🔍 搜索测试")
 print_separator
 print(f" 集合: {collection_name}")
 print(f" 查询: {query}")
 print(f" Top-K: {top_k}")
 if language:
 print(f" 语言过滤: {language}")
 print_separator
 # 1. 生成查询向量
 print("\n⏳ 生成查询向量...")
 if embedding_url:
 print(f" 使用手动配置: {embedding_url}")
 query_vector = await generate_embedding_manual(
 query, embedding_url, embedding_model, embedding_key
 )
 else:
 try:
 query_vector = await EmbeddingService.generate_embedding(query)
 except Exception as e:
 print(f" ❌ 从系统配置获取失败: {e}")
 print(" 💡 提示: 可以使用 --embedding-url 参数手动指定 API 地址")
 return
 if not query_vector:
 print(" ❌ 无法生成查询向量，请检查 Embedding API 配置")
 return
 print(f" ✅ 向量维度: {len(query_vector)}")
 # 调整向量维度（如果指定）
 if embedding_dim and len(query_vector) != embedding_dim:
 original_dim = len(query_vector)
 if len(query_vector) < embedding_dim:
 # 填充零
 query_vector = query_vector + [0.0] * (embedding_dim - len(query_vector))
 print(f" ⚠️ 向量已填充: {original_dim} → {embedding_dim}")
 else:
 # 截断
 query_vector = query_vector[:embedding_dim]
 print(f" ⚠️ 向量已截断: {original_dim} → {embedding_dim}")
 # 2. 执行搜索
 print("\n⏳ 执行向量搜索...")
 filters = {}
 if language:
 filters["language"] = language
 from asgiref.sync import sync_to_async
 # KEEP: Qdrant SDK 同步限制（测试脚本）
 results = await sync_to_async(QdrantService.search)(
 repository_id=repository_id,
 query_vector=query_vector,
 top_k=top_k,
 filters=filters if filters else None,
 )
 if not results:
 print(" ❌ 没有找到任何结果")
 return
 # 3. 显示结果
 print(f"\n✅ 找到 {len(results)} 个结果:\n")
 print_separator("=")
 for i, result in enumerate(results, 1):
 payload = result.get("payload", {})
 score = result.get("score", 0)
 file_path = payload.get("file_path", "unknown")
 language = payload.get("language", "unknown")
 chunk_type = payload.get("chunk_type", "unknown")
 name = payload.get("name", "")
 start_line = payload.get("start_line", 0)
 end_line = payload.get("end_line", 0)
 print(f"[{i}] 相似度: {score:.4f}")
 print(f" 文件: {file_path}")
 print(f" 类型: {chunk_type} | 语言: {language} | 行: {start_line}-{end_line}")
 if name:
 print(f" 名称: {name}")
 # 显示代码片段 (如果有)
 content = payload.get("content", "")
 if content:
 # 截取前 300 个字符
 preview = content[:300]
 if len(content) > 300:
 preview += "..."
 print(" 代码预览:")
 for line in preview.split("\n")[:8]:
 print(f" {line}")
 if content.count("\n") > 8:
 print(f" ... ({content.count(chr(10))} 行)")
 print_separator
async def test_embedding_service -> None:
 """测试 Embedding 服务"""
 print("\n🧪 测试 Embedding 服务:")
 print_separator
 config = await EmbeddingService.get_config
 print(f" API URL: {config.get('api_url', '未配置')}")
 print(f" Model: {config.get('model', '未配置')}")
 print(f" Dimension: {config.get('dimension', '未配置')}")
 result = await EmbeddingService.test_connection
 print(f" 状态: {result.get('status')}")
 if result.get("status") == "healthy":
 print(f" 实际维度: {result.get('dimension')}")
 else:
 print(f" 错误: {result.get('message')}")
def main -> None:
 parser = argparse.ArgumentParser(
 description="Qdrant 向量召回测试工具",
 formatter_class=argparse.RawDescriptionHelpFormatter,
 epilog=__doc__,
 )
 parser.add_argument("--repo-id", "-r", help="仓库 ID")
 parser.add_argument("--query", "-q", help="搜索查询文本")
 parser.add_argument("--top-k", "-k", type=int, default=5, help="返回结果数量 (默认: 5)")
 parser.add_argument("--language", "-l", help="按语言过滤 (如: python, typescript)")
 parser.add_argument("--list-collections", action="store_true", help="列出所有集合")
 parser.add_argument("--stats", action="store_true", help="显示集合统计信息")
 parser.add_argument("--test-embedding", action="store_true", help="测试 Embedding 服务")
 parser.add_argument("--health", action="store_true", help="检查 Qdrant 健康状态")
 parser.add_argument("--embedding-url", help="手动指定 Embedding API URL")
 parser.add_argument("--embedding-model", default="BAAI/bge-m3", help="Embedding 模型名称")
 parser.add_argument("--embedding-key", help="Embedding API Key")
 parser.add_argument("--embedding-dim", type=int, help="指定 Embedding 维度 (用于截断或填充)")
 args = parser.parse_args
 # 健康检查
 if args.health:
 print("\n🏥 Qdrant 健康检查:")
 print_separator
 result = QdrantService.health_check
 print(f" 状态: {result.get('status')}")
 if result.get("status") == "healthy":
 print(f" 集合数量: {result.get('collections_count')}")
 else:
 print(f" 错误: {result.get('error')}")
 return
 # 列出集合
 if args.list_collections:
 list_collections
 return
 # 测试 Embedding
 if args.test_embedding:
 asyncio.run(test_embedding_service)
 return
 # 显示统计
 if args.stats:
 if not args.repo_id:
 print("❌ 请指定 --repo-id")
 sys.exit(1)
 show_collection_stats(args.repo_id)
 return
 # 执行搜索
 if args.query:
 if not args.repo_id:
 print("❌ 请指定 --repo-id")
 sys.exit(1)
 asyncio.run(
 search_qdrant(
 repository_id=args.repo_id,
 query=args.query,
 top_k=args.top_k,
 language=args.language,
 embedding_url=args.embedding_url,
 embedding_model=args.embedding_model,
 embedding_key=args.embedding_key,
 embedding_dim=args.embedding_dim,
 )
 )
 return
 # 默认显示帮助
 parser.print_help
if __name__ == "__main__":
 main
