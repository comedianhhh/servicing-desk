#!/usr/bin/env sh
# Build the image, tag it by content id, point kustomize at that tag, apply. Immutable tags mean a rebuild
# always rolls out; the same content twice is a no-op.
set -eu
cd "$(dirname "$0")/.."
docker build -q -t servicing-desk:dev backend >/dev/null
TAG=$(docker image inspect servicing-desk:dev --format '{{.Id}}' | cut -c8-19)
docker tag servicing-desk:dev "servicing-desk:$TAG"
sed -i "s/^    newTag: .*/    newTag: $TAG/" k8s/kustomization.yaml
kubectl apply -k k8s
echo "deployed servicing-desk:$TAG"
