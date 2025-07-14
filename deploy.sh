cd app
az acr build --registry container7 --image aks-api:latest .
cd ../code_runner
az acr build --registry container7 --image code-runner:latest .

cd ../app
kubectl apply -f deploy.yaml

kubectl rollout restart deployment aks-api