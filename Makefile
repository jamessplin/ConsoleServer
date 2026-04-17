# Makefile for Console Server Project


.PHONY: install uninstall start stop test lint clean sync_base_port

install:
	@BASE_PORT=$$(python3 -c "import json; print(json.load(open('config/config.json'))['info']['base_port'])"); \
	echo "[INFO] BASE_PORT is $$BASE_PORT"; \
	sed 's/{{BASE_PORT}}/'"$$BASE_PORT"'/g' src/console-ssh-dispatch.sh.j2 > src/console-ssh-dispatch.sh; \
	chmod +x src/console-ssh-dispatch.sh; \
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
	# 3. Run setup_ssh_dispatch.py with correct port range and options (match install script)
	python3 src/setup_ssh_dispatch.py --start $(shell expr $(BASE_PORT) + 1) --end $(shell expr $(BASE_PORT) + 24) \
		--address-family inet \
		--port22-dualstack \
		--max-ports-per-sshd 16 \
		--split-at-port $(shell expr $(BASE_PORT) + 12) \
		--enable-second-sshd \
		--second-sshd-config /etc/ssh/sshd_config_seriald2 \
		--second-sshd-service ssh-seriald2.service
	# 4. Reminder: Restart services to apply changes
	@echo "[INFO] Base port updated. Please restart seriald and sshd services to apply changes:"
	@echo "       sudo systemctl restart seriald.service sshd.service"
