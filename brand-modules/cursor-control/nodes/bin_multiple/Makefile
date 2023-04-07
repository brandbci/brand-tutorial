PROJECT=bin_multiple

ifneq ($(CONDA_DEFAULT_ENV),rt)
$(error real-time conda env (rt) not active)
endif

ROOT ?=../..
include $(ROOT)/setenv.mk

PYTHON_VERSION=3.8 # This works for rt env
PYTHON_LIB=python$(PYTHON_VERSION)

LIBPYTHON=$(CONDA_PREFIX)/lib/
INCPYTHON=$(CONDA_PREFIX)/include/$(PYTHON_LIB)

TARGET=$(PROJECT).bin
CYTHON_TARGET=$(GENERATED_PATH)/$(PROJECT).c

all:
	cp $(PROJECT).py $(PROJECT).pyx
	cython -3 --embed $(PROJECT).pyx -o $(CYTHON_TARGET)
	gcc $(CYTHON_TARGET) -o $(TARGET) -I $(INCPYTHON) -L $(LIBPYTHON)  -Wl,-rpath=$(LIBPYTHON) -l$(PYTHON_LIB) -lpthread -lm -lutil -ldl
	$(RM) $(PROJECT).pyx
clean:
	$(RM) $(CYTHON_TARGET) $(PROJECT).pyx
