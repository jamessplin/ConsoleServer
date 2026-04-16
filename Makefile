# Makefile for Console Server Project


.PHONY: install uninstall start stop test lint clean sync_base_port

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

sync_base_port:
	@if [ -z "$(BASE_PORT)" ]; then \
	  echo "Usage: make sync_base_port BASE_PORT=20000"; \
	  exit 1; \
	fi
	# 1. Update config.json base port for all lines
	python3 config/update_base_port.py config/config.json $(BASE_PORT)
	# 2. Generate console-ssh-dispatch.sh from template
	sed 's/{{BASE_PORT}}/'"$(BASE_PORT)"'/g' src/console-ssh-dispatch.sh.j2 > src/console-ssh-dispatch.sh
	chmod +x src/console-ssh-dispatch.sh
	# 3. Run setup_ssh_dispatch.py with correct port range
	python3 src/setup_ssh_dispatch.py --start $(shell expr $(BASE_PORT) + 1) --end $(shell expr $(BASE_PORT) + 24)
	# 3. Reminder: Deployment is not complete until you run 'make uninstall' and 'make install'
	@echo "[INFO] Base port updated. Please run 'make uninstall' and then 'make install' to apply changes."
