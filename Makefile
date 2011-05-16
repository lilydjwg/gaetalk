.PHONY: all clean

all: README.html

README.html: README.mkd
	@echo '<!DOCTYPE html>' > $@
	@echo '<link rel="stylesheet" href="css/markdown.css" type="text/css" />' >> $@
	@echo '<title>lilytalk 介绍</title>' >> $@
	Markdown.pl < $< >> $@
clean:
	-rm *.html
