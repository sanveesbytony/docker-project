#!/bin/bash

# SteadFast Return Scraper Manager Script

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_info() {
    echo -e "${YELLOW}ℹ $1${NC}"
}

check_env_file() {
    if [ ! -f .env ]; then
        print_error ".env file not found!"
        print_info "Creating .env from .env.example..."
        if [ -f .env.example ]; then
            cp .env.example .env
            print_info "Please edit .env file with your credentials"
            exit 1
        else
            print_error ".env.example not found!"
            exit 1
        fi
    fi
}

check_data_dir() {
    if [ ! -d data ]; then
        mkdir -p data
        print_success "Created data directory"
    fi
}

case "$1" in
    build)
        print_info "Building Docker image..."
        docker-compose build
        print_success "Build completed"
        ;;
    
    start)
        check_env_file
        check_data_dir
        print_info "Starting scraper..."
        docker-compose up -d
        print_success "Scraper started in background"
        print_info "View logs with: ./manage.sh logs"
        ;;
    
    stop)
        print_info "Stopping scraper..."
        docker-compose down
        print_success "Scraper stopped"
        ;;
    
    restart)
        print_info "Restarting scraper..."
        docker-compose restart
        print_success "Scraper restarted"
        ;;
    
    logs)
        docker-compose logs -f
        ;;
    
    status)
        docker-compose ps
        ;;
    
    run)
        check_env_file
        check_data_dir
        print_info "Running scraper (foreground)..."
        docker-compose up
        ;;
    
    clean)
        print_info "Removing containers and images..."
        docker-compose down --rmi all
        print_success "Cleanup completed"
        ;;
    
    shell)
        print_info "Opening shell in container..."
        docker-compose exec return-scraper /bin/bash
        ;;
    
    *)
        echo "SteadFast Return Scraper Manager"
        echo ""
        echo "Usage: $0 {build|start|stop|restart|logs|status|run|clean|shell}"
        echo ""
        echo "Commands:"
        echo "  build    - Build Docker image"
        echo "  start    - Start scraper in background"
        echo "  stop     - Stop scraper"
        echo "  restart  - Restart scraper"
        echo "  logs     - View scraper logs (live)"
        echo "  status   - Show container status"
        echo "  run      - Run scraper in foreground"
        echo "  clean    - Remove containers and images"
        echo "  shell    - Open shell in running container"
        exit 1
        ;;
esac
