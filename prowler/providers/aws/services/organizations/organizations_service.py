import json
from typing import Optional

from botocore.client import ClientError
from pydantic import BaseModel

from prowler.lib.logger import logger
from prowler.lib.scan_filters.scan_filters import is_resource_filtered
from prowler.providers.aws.aws_provider import generate_regional_clients


################## Organizations
class Organizations:
    def __init__(self, audit_info):
        self.service = "organizations"
        self.session = audit_info.audit_session
        self.audited_account = audit_info.audited_account
        self.audit_resources = audit_info.audit_resources
        global_client = generate_regional_clients(
            self.service, audit_info, global_service=True
        )
        self.client = list(global_client.values())[0]
        self.region = self.client.region
        self.organizations = []
        self.policies = []
        self.delegated_administrators = []
        self.__describe_organization__()

    def __describe_organization__(self):
        logger.info("Organizations - Describe Organization...")

        try:
            # Check if Organizations is in-use
            try:
                organization_desc = self.client.describe_organization()["Organization"]
                organization_arn = organization_desc.get("Arn")
                organization_id = organization_desc.get("Id")
                organization_master_id = organization_desc.get("MasterAccountId")
                organization_available_policy_types = organization_desc.get(
                    "AvailablePolicyTypes"
                )
                # Fetch policies for organization:
                organization_policies = self.__list_policies__(
                    organization_available_policy_types
                )
                # Fetch delegated administrators for organization:
                organization_delegated_administrator = (
                    self.__list_delegated_administrators__()
                )
            except ClientError as error:
                if (
                    error.response["Error"]["Code"]
                    == "AWSOrganizationsNotInUseException"
                ):
                    self.organizations.append(
                        Organization(
                            arn="",
                            id="AWS Organization",
                            status="NOT_AVAILABLE",
                            master_id="",
                        )
                    )
                else:
                    logger.error(
                        f"{self.region} -- {error.__class__.__name__}[{error.__traceback__.tb_lineno}]: {error}"
                    )
            else:
                if not self.audit_resources or (
                    is_resource_filtered(organization_arn, self.audit_resources)
                ):
                    self.organizations.append(
                        Organization(
                            arn=organization_arn,
                            id=organization_id,
                            status="ACTIVE",
                            master_id=organization_master_id,
                            policies=organization_policies,
                            delegated_administrators=organization_delegated_administrator,
                        )
                    )
                else:
                    # is filtered
                    self.organizations.append(
                        Organization(
                            arn="",
                            id="AWS Organization",
                            status="NOT_AVAILABLE",
                            master_id="",
                        )
                    )

        except Exception as error:
            logger.error(
                f"{self.region} -- {error.__class__.__name__}[{error.__traceback__.tb_lineno}]: {error}"
            )

    # I'm using list_policies instead of list_policies_for_target, because the last one only returns "Attached directly" policies but not "Inherited from..." policies.
    def __list_policies__(self, enabled_policy_types):
        logger.info("Organizations - List policies...")

        try:
            list_policies_paginator = self.client.get_paginator("list_policies")
            for policy_type in enabled_policy_types:
                logger.info(
                    "Organizations - List policies... - Type: %s",
                    policy_type.get("Type"),
                )
                for page in list_policies_paginator.paginate(
                    Filter=policy_type.get("Type")
                ):
                    for policy in page["Policies"]:
                        policy_content = self.__describe_policy__(policy.get("Id"))
                        policy_targets = self.__list_targets_for_policy__(
                            policy.get("Id")
                        )
                        self.policies.append(
                            Policy(
                                arn=policy.get("Arn"),
                                id=policy.get("Id"),
                                type=policy.get("Type"),
                                aws_managed=policy.get("AwsManaged"),
                                content=policy_content,
                                targets=policy_targets,
                            )
                        )

        except ClientError as error:
            if error.response["Error"]["Code"] == "AccessDeniedException":
                self.policies = None

        except Exception as error:
            logger.error(
                f"{self.region} -- {error.__class__.__name__}[{error.__traceback__.tb_lineno}]: {error}"
            )

        finally:
            return self.policies

    def __describe_policy__(self, policy_id):
        logger.info("Organizations - Describe policy: %s ...", policy_id)

        # This operation can be called only from the organization’s management account or by a member account that is a delegated administrator for an Amazon Web Services service.
        try:
            policy_desc = self.client.describe_policy(PolicyId=policy_id)["Policy"]
            policy_content = policy_desc["Content"]
            policy_content_json = json.loads(policy_content)
        except Exception as error:
            logger.error(
                f"{self.region} -- {error.__class__.__name__}[{error.__traceback__.tb_lineno}]: {error}"
            )
        finally:
            return policy_content_json

    def __list_targets_for_policy__(self, policy_id):
        logger.info("Organizations - List Targets for policy: %s ...", policy_id)

        try:
            targets_for_policy = self.client.list_targets_for_policy(
                PolicyId=policy_id
            )["Targets"]
        except Exception as error:
            logger.error(
                f"{self.region} -- {error.__class__.__name__}[{error.__traceback__.tb_lineno}]: {error}"
            )
        finally:
            return targets_for_policy

    def __list_delegated_administrators__(self):
        logger.info("Organizations - List Delegated Administrators")

        try:
            list_delegated_administrators_paginator = self.client.get_paginator(
                "list_delegated_administrators"
            )
            for page in list_delegated_administrators_paginator.paginate():
                for delegated_administrator in page["DelegatedAdministrators"]:
                    self.delegated_administrators.append(
                        DelegatedAdministrator(
                            arn=delegated_administrator.get("Arn"),
                            id=delegated_administrator.get("Id"),
                            name=delegated_administrator.get("Name"),
                            email=delegated_administrator.get("Email"),
                            status=delegated_administrator.get("Status"),
                            joinedmethod=delegated_administrator.get("JoinedMethod"),
                        )
                    )

        except ClientError as error:
            if error.response["Error"]["Code"] == "AccessDeniedException":
                self.delegated_administrators = None

        except Exception as error:
            logger.error(
                f"{self.region} -- {error.__class__.__name__}[{error.__traceback__.tb_lineno}]: {error}"
            )

        finally:
            return self.delegated_administrators


class Policy(BaseModel):
    arn: str
    id: str
    type: str
    aws_managed: bool
    content: dict = {}
    targets: Optional[list] = []


class DelegatedAdministrator(BaseModel):
    arn: str
    id: str
    name: str
    email: str
    status: str
    joinedmethod: str


class Organization(BaseModel):
    arn: str
    id: str
    status: str
    master_id: str
    policies: list[Policy] = None
    delegated_administrators: list[DelegatedAdministrator] = None
