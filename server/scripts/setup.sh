#!/bin/bash
# Friday AI Dev Agent - Setup Script
set -e
echo "🚀 Friday AI Dev Agent Setup"
echo "================================"
# Check prerequisites
check_prerequisites {
 echo "📋 Checking prerequisites..."
 # Check Docker
 if ! command -v docker &> /dev/null; then
 echo "❌ Docker is not installed. Please install Docker first."
 exit 1
 fi
 echo "✅ Docker is installed"
 # Check Docker Compose
 if ! docker compose version &> /dev/null; then
 echo "❌ Docker Compose is not installed. Please install Docker Compose first."
 exit 1
 fi
 echo "✅ Docker Compose is installed"
 # Check if Docker daemon is running
 if ! docker info &> /dev/null; then
 echo "❌ Docker daemon is not running. Please start Docker."
 exit 1
 fi
 echo "✅ Docker daemon is running"
}
# Create environment file
setup_env {
 echo ""
 echo "📝 Setting up environment..."
 if [ ! -f .env ]; then
 cp .env.example .env
 echo "✅ Created .env from .env.example"
 echo ""
 echo "⚠️ Please edit .env and fill in the required values:"
 echo " - FRIDAY_ENCRYPTION_KEY"
 echo " - FRIDAY_FEISHU_APP_ID"
 echo " - FRIDAY_FEISHU_APP_SECRET"
 echo " - FRIDAY_FEISHU_VERIFICATION_TOKEN"
 echo " - ANTHROPIC_API_KEY"
 echo ""
 else
 echo "✅ .env already exists"
 fi
}
# Generate encryption key if not set
generate_encryption_key {
 if grep -q "FRIDAY_ENCRYPTION_KEY=$" .env 2>/dev/null || grep -q "FRIDAY_ENCRYPTION_KEY=\"\"" .env 2>/dev/null; then
 echo "🔑 Generating encryption key..."
 KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key.decode)" 2>/dev/null || echo "")
 if [ -n "$KEY" ]; then
 sed -i.bak "s/FRIDAY_ENCRYPTION_KEY=.*/FRIDAY_ENCRYPTION_KEY=$KEY/" .env
 rm -f .env.bak
 echo "✅ Encryption key generated"
 else
 echo "⚠️ Could not generate encryption key. Please set it manually."
 fi
 fi
}
# Build images
build_images {
 echo ""
 echo "🏗️ Building Docker images..."
 docker compose build
 echo "✅ Images built successfully"
}
# Create data directory
create_data_dir {
 echo ""
 echo "📁 Creating data directory..."
 mkdir -p data
 echo "✅ Data directory created"
}
# Start services
start_services {
 echo ""
 echo "🚀 Starting services..."
 docker compose up -d
 echo "✅ Services started"
 echo ""
 echo "📊 Service status:"
 docker compose ps
}
# Main
main {
 check_prerequisites
 setup_env
 generate_encryption_key
 create_data_dir
 build_images
 start_services
 echo ""
 echo "================================"
 echo "🎉 Friday AI Dev Agent is ready!"
 echo ""
 echo "📖 API Documentation: http://localhost:8000/docs"
 echo "❤️ Health Check: http://localhost:8000/health"
 echo ""
 echo "📌 Next steps:"
 echo " 1. Configure Feishu webhook to point to your server"
 echo " 2. Create a project via POST /api/projects/"
 echo " 3. Add Git credentials via POST /api/projects/{id}/credentials"
 echo ""
 echo "📝 Useful commands:"
 echo " - View logs: docker compose logs -f"
 echo " - Stop: docker compose down"
 echo " - Restart: docker compose restart"
}
main "$@"