#!/bin/bash
set -e

source {{devstack_location}}/functions
source {{devstack_location}}/functions-common
branch={{zuul_branch}}

echo "Before updating nova flavors:"
nova flavor-list

if [ "$branch" == "stable/newton" ] || [ "$branch" == "stable/liberty" ] || [ "$branch" == "stable/mitaka" ]; then
    nova flavor-delete 42
    nova flavor-delete 84
    nova flavor-delete 451
fi

nova flavor-create m1.nano 42 512 1 1
nova flavor-create m1.micro 84 128 2 1
nova flavor-create m1.heat 451 512 5 1

echo "After updating nova flavors:"
nova flavor-list

echo 'set global max_connections = 1000;' | mysql

# Add DNS config to the private network
subnet_id=`neutron net-show private | grep subnets | awk '{print $4}'`
neutron subnet-update $subnet_id --dns_nameservers list=true {{nameservers}}

