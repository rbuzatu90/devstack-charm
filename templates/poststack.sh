#!/bin/bash

set +e

function checkservicestatus () {
    local SERVICE=$1
    local INTERVAL=20
    local MAX_RETRIES=10
    local COUNTER=0

    if [ "$SERVICE" == "nova" ]; then
        STATUS_LIST="nova service-list"
        SERVICE_COUNT="2"
        CMD='nova service-list | grep nova-compute | grep -c -w up'
    elif [ "$SERVICE" == "neutron-hyperv" ]; then
        STATUS_LIST="neutron agent-list"
        SERVICE_COUNT="2"
        CMD='neutron agent-list | grep -c "HyperV agent.*:-)"'
    else
        STATUS_LIST="neutron agent-list"
        SERVICE_COUNT="3"
        CMD='neutron agent-list | grep -c "Open vSwitch agent.*:-)"'
    fi

    while [ $COUNTER -lt $MAX_RETRIES ]; do
	RUN_CMD=$(eval $CMD)
        if [ "$RUN_CMD" == $SERVICE_COUNT ]; then
            echo "$SERVICE HyperV services are up"
            return 0
        else
            echo "Both $SERVICE HyperV services must be up"
            $STATUS_LIST
        fi
        let COUNTER=COUNTER+1

        if [ -n "$INTERVAL" ]; then
            sleep $INTERVAL
        fi
    done
    return $EXIT
}


source /home/ubuntu/devstack/functions
source /home/ubuntu/devstack/functions-common
source /home/ubuntu/keystonerc


# Configure tempest.conf
TEMPEST_CONFIG=/opt/stack/tempest/etc/tempest.conf

iniset $TEMPEST_CONFIG compute volume_device_name "sdb"
iniset $TEMPEST_CONFIG compute-feature-enabled rdp_console true
iniset $TEMPEST_CONFIG compute-feature-enabled block_migrate_cinder_iscsi False

iniset $TEMPEST_CONFIG scenario img_dir "/home/ubuntu/devstack/files/images/"
iniset $TEMPEST_CONFIG scenario img_file cirros-0.3.3-x86_64.vhdx
iniset $TEMPEST_CONFIG scenario img_disk_format vhd

IMAGE_REF=$(iniget $TEMPEST_CONFIG compute image_ref)
iniset $TEMPEST_CONFIG compute image_ref_alt $IMAGE_REF

iniset $TEMPEST_CONFIG compute ssh_user cirros
iniset $TEMPEST_CONFIG compute image_alt_ssh_user cirros
iniset $TEMPEST_CONFIG compute image_ssh_user cirros
iniset $TEMPEST_CONFIG compute ssh_timeout 180

iniset $TEMPEST_CONFIG compute build_timeout 300
iniset $TEMPEST_CONFIG orchestration build_timeout 600
iniset $TEMPEST_CONFIG volume build_timeout 300
iniset $TEMPEST_CONFIG boto build_timeout 300

iniset $TEMPEST_CONFIG compute ssh_timeout 600
iniset $TEMPEST_CONFIG compute allow_tenant_isolation True

# Check for nova join (must equal 2)
checkservicestatus "nova"

# Check for neutron join (must equal 2)
NET_TYPE={{ml2_mechanism}}
if [ "$NET_TYPE" == "hyperv" ]; then
        checkservicestatus "neutron-hyperv"
else
        checkservicestatus "neutron-ovs"
fi

# For master of Ocata branch activate cell_v2
ZUUL_BRANCH={{zuul_branch}}
if [[ "$ZUUL_BRANCH" == "master" ]] || [[ "$ZUUL_BRANCH" == "stable/ocata" ]]; then
        url="rabbit://{{rabbit_user}}:{{password}}@{{devstack_ip}}:5672"
        echo "running: nova-manage cell_v2 --transport-url $url"
        nova-manage cell_v2 simple_cell_setup --transport-url $url >> /opt/stack/logs/screen/create_cell.log
fi

