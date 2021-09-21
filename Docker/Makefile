NAME        := srl/docter-agent
LAST_COMMIT := $(shell sh -c "git log -1 --pretty=%h")
TODAY       := $(shell sh -c "date +%Y%m%d_%H%M")
TAG         := ${TODAY}.${LAST_COMMIT}
IMG         := ${NAME}:${TAG}

# HTTP_PROXY  := "http://proxy.lbs.alcatel-lucent.com:8000"

ifndef SR_LINUX_RELEASE
override SR_LINUX_RELEASE="latest"
endif

build:
	echo "Building agent for ${SR_LINUX_RELEASE}..."
	cd .. && docker build --build-arg SRL_AUTO_CONFIG_RELEASE=${TAG} \
	  --build-arg http_proxy=${HTTP_PROXY} --build-arg https_proxy=${HTTP_PROXY} \
	  --build-arg SR_LINUX_RELEASE="${SR_LINUX_RELEASE}" \
		-f Docker/Dockerfile -t ${IMG} .
	sudo docker tag ${IMG} ${NAME}:${SR_LINUX_RELEASE}

build-submodules:
	make -C ../srl-baseimage
	make -C ../srl-self-organizing/Docker

all: build-submodules build
