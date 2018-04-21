
.PHONY: build


install:
	@echo "\n -----------------------------"
	@echo " * installing node dependancies"
	node -v
	@echo " ------------------------------\n"
	npm install jade --save

	@echo "\n -----------------------------"
	@echo " * installing python 3 dependancies"
	node -v
	@echo " ------------------------------\n"

	pip install -r requirements.txt


jade:
	@echo "\n ---------------------------"
	@echo " * Building flask templates"
	@echo " * Requires NODEJS + jade "
	@echo " ---------------------------\n"

	cd ./templates && node ../node_modules/jade/bin/jade.js -P *.jade

statics :
	@echo "\n ---------------------------"
	@echo " * Building statics"
	@echo " ---------------------------\n"



build : jade statics

run : build
	export APP_DEBUG=true; python app.py  --port 5009
