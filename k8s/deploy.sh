#!/usr/bin/env sh
# Build both images, tag them by content id, point kustomize at those tags, apply. Immutable tags mean a
# rebuild always rolls out; the same content twice is a no-op.
set -eu
cd "$(dirname "$0")/.."
docker build -q -t servicing-desk:dev backend >/dev/null
docker build -q -t servicing-desk-web:dev frontend >/dev/null
TAG=$(docker image inspect servicing-desk:dev --format '{{.Id}}' | cut -c8-19)
WEB=$(docker image inspect servicing-desk-web:dev --format '{{.Id}}' | cut -c8-19)
docker tag servicing-desk:dev "servicing-desk:$TAG"
docker tag servicing-desk-web:dev "servicing-desk-web:$WEB"
# each image's newTag is the line after its name
sed -i "/name: servicing-desk-web$/{n;s/newTag: .*/newTag: $WEB/}" k8s/kustomization.yaml
sed -i "/name: servicing-desk$/{n;s/newTag: .*/newTag: $TAG/}" k8s/kustomization.yaml
kubectl apply -k k8s
echo "deployed servicing-desk:$TAG servicing-desk-web:$WEB"
