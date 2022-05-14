-include .env
export

current_dir = $(shell pwd)

init:
	test -f .env || echo "TELEGRAM_API_KEY=<api_key>" > .env
	test -f chats.json || echo "[]" > chats.json

install:
	poetry install

build: init
	docker build --no-cache -t burgerbot .

run-docker: build
	docker run \
	-e TELEGRAM_API_KEY=$(TELEGRAM_API_KEY) \
	--mount type=bind,source=$(current_dir)/chats.json,target=/app/chats.json \
	burgerbot

run-dev: install
	poetry run python burgerbot/burgerbot.py
