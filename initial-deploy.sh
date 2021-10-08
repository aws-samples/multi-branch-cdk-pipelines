#!/usr/bin/env bash

#Including .ini file
source config.ini
echo ${region}
echo ${repository_name}

while [ $# -gt 0 ]; do
   if [[ $1 == *"--"* ]]; then
        param="${1/--/}"
        declare $param="$2"
   fi
  shift
done

if [[ -z "$dev_account_id" || -z "$dev_profile_name" || -z "$prod_account_id" || -z "$prod_profile_name" ]]; then
  echo "The following parameters are required: --dev_account_id, --dev_profile_name, --prod_account_id, --prod_profile_name"
  exit
fi

echo "Dev account id: $dev_account_id"
echo "Dev profile name: $dev_profile_name"
echo "Prod account id: $prod_account_id"
echo "Prod profile name: $prod_profile_name"
echo "Region: $region"
echo "Repository name: $repository_name"

export DEV_ACCOUNT_ID=$dev_account_id
export PROD_ACCOUNT_ID=$prod_account_id

# retrieve default branch
export BRANCH=$(aws codecommit get-repository --repository-name ${repository_name} --region ${region} --output json | jq -r '.repositoryMetadata.defaultBranch')

# bootstrap Development AWS Account
npx cdk bootstrap --profile $dev_profile_name --cloudformation-execution-policies arn:aws:iam::aws:policy/AdministratorAccess aws://$dev_account_id/${region}

# bootstrap Production AWS Account and add trust to development account where pipeline resides
npx cdk bootstrap --profile $prod_profile_name --trust $dev_account_id --cloudformation-execution-policies arn:aws:iam::aws:policy/AdministratorAccess aws://$prod_account_id/${region}

# deploy pipeline
npx cdk deploy cdk-pipelines-multi-branch-$BRANCH

exit $?

