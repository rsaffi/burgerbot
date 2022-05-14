include .env
export

current_dir = $(shell pwd)

build:
	docker build --no-cache -t burgerbot .

run: build
	docker run \
	-e TELEGRAM_API_KEY=$(TELEGRAM_API_KEY) \
	--mount type=bind,source=$(current_dir)/chats.json,target=/app/chats.json \
	burgerbot
