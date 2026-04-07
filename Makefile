# Makefile for Console Server Project

.PHONY: install uninstall start stop test lint clean

install:
	sudo ./console

uninstall:
	sudo ./console --remove

start:
	sudo systemctl start seriald.service

stop:
	sudo systemctl stop seriald.service

test:
	@echo "No tests defined yet. Add your test commands here."

lint:
	@echo "No linter defined yet. Add your lint commands here."

clean:
	@echo "No clean steps defined yet. Add your clean commands here."
