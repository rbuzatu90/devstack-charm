#!/bin/bash

while [ $# -gt 0 ];
do
    case $1 in
        --branch)
            ZUUL_BRANCH=$2
            shift;;
        --project)
            ZUUL_PROJECT=$2
            shift;;
        --devstack-git-archive)
            DEVSTACK_ARCHIVE_URL=$2
            shift;;
        --stack-git-archive)
            STACK_ARCHIVE_URL=$2
            shift;;
    esac
    shift
done

if [ -z "$ZUUL_BRANCH" ]; then
    echo "zuul branch argument is missing"
    exit 1
fi

if [ -z "$ZUUL_PROJECT" ]; then
    echo "zuul project argument is missing"
    exit 1
fi

PROJECT_NAME=$(basename $ZUUL_PROJECT)

echo "Updating project repos for:" 
echo "    branch: $ZUUL_BRANCH"
echo "    build-for: $ZUUL_PROJECT"
echo "    devstack-git-archive: $DEVSTACK_ARCHIVE_URL"
echo "    stack-git-archive: $STACK_ARCHIVE_URL"

if [ ! -z "$DEVSTACK_ARCHIVE_URL" ]; then
    if [ -d "/home/ubuntu/devstack" ]; then
        rm -rf /home/ubuntu/devstack
    fi

    if [ ! -f "/home/ubuntu/devstack.tar.gz" ]; then
        echo "Downloading devstack git archive: $DEVSTACK_ARCHIVE_URL"
        wget -O /home/ubuntu/devstack.tar.gz $DEVSTACK_ARCHIVE_URL
    else
        echo "Found /home/ubuntu/devstack.tar.gz, will not download again."
    fi

    tar -zxf /home/ubuntu/devstack.tar.gz -C /home/ubuntu/

    if [ -d "/home/ubuntu/devstack" ]; then
        echo "Updating devstack git repo"
        pushd /home/ubuntu/devstack
        if [ -d ".git" ]; then
            git reset --hard
            git clean -f -d
            git fetch
            git checkout "$ZUUL_BRANCH" || echo "Failed to switch branch $ZUUL_BRANCH"
            git pull
            echo "Devstack branch:"
            git branch
            echo "Devstack git log:"
            git log -10 --pretty=format:"%h - %an, %ae,  %ar : %s"
        else
            echo "Skipping /home/ubuntu/devstack, not a git repo"
        fi
        popd
    else
        echo "/home/ubuntu/devstack folder not found, not updating"
    fi
else
    echo "devstack-git-archive missing, skipping updating devstack"
fi


if [ ! -z "$STACK_ARCHIVE_URL" ]; then
    if [ -d "/opt/stack" ]; then
        rm -rf /opt/stack
    fi

    if [ ! -f "/home/ubuntu/stack.tar.gz" ]; then
        echo "Downloading stack git archive: $STACK_ARCHIVE_URL"
        wget -O /home/ubuntu/stack.tar.gz $STACK_ARCHIVE_URL
    else
        echo "Found /home/ubuntu/stack.tar.gz, will not download again."
    fi

    sudo tar -zxf /home/ubuntu/stack.tar.gz -C /opt/
    sudo chown -R ubuntu /opt/stack
    
    if [ -d "/opt/stack" ]; then
        pushd /opt/stack
        find . -name *pyc -print0 | xargs -0 rm -f
        for i in $(ls -A); do
            if [ "$i" != "$PROJECT_NAME" ]; then
                pushd "$i"
                if [ -d ".git" ]; then
                    git reset --hard
                    git clean -f -d
                    git fetch
                    git checkout "$ZUUL_BRANCH" || echo "Failed to switch branch $ZUUL_BRANCH"
                    git pull
                    echo "/opt/stack/$i branch:"
                    git branch
                    echo "/opt/stack/$i git log:"
                    git log -10 --pretty=format:"%h - %an, %ae,  %ar : %s"
                else
                    echo "Skipping /opt/stack/$i, not a git repo"
                fi
                popd
            fi
        done
        popd
    else
        echo "/opt/stack folder not found, not updating"
    fi
else
    echo "stack-git-archive missing, skipping updating stack"
fi
