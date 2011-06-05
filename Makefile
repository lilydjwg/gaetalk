.PHONY: all clean

all: README.html

README.html: README.mkd
	@echo '<!DOCTYPE html>' > $@
	@echo '<link rel="stylesheet" href="css/markdown.css" type="text/css" />' >> $@
	@echo '<meta http-equiv="content-type" content="text/html; charset=utf-8" />' >> $@
	@echo '<title>gaetalk 介绍</title>' >> $@
	markdown < $< >> $@
clean:
	-rm *.html
