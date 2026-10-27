"""Spec 117 fixes: after `--switch` on the apply path the new active cluster has its ScheduledBackup (AC-117.13)."""
import yaml

from backup_fixtures import kube  # noqa: F401  (fixture)
from test_backup_117_restore import APP, DEV, NS, repo, restore, switch_world  # noqa: F401  (repo is a fixture)


def test_switch_on_the_apply_path_leaves_a_scheduled_backup_for_the_new_cluster_ac_117_13(repo, kube, capsys):  # AC-117.13
    switch_world(repo, kube)
    kube.store["scheduledbackup"] = [{"metadata": {"name": "shop-orders-db", "namespace": NS}, "spec": {"cluster": {"name": "shop-orders-db"}}}]

    def apply_k(k, args):
        # a ScheduledBackup's cluster cannot change in place: applying over the old one fails; applying after the delete creates it
        doc = yaml.safe_load((repo / APP / "addons/dev/orders-db/scheduledbackup.yaml").read_text())
        have = [o for o in k.store["scheduledbackup"] if o["metadata"]["name"] == doc["metadata"]["name"]]
        assert not have, "the old ScheduledBackup must be deleted before the apply"
        k.store["scheduledbackup"].append(doc)

    def delete(args, stdin):
        if args[0] == "delete" and args[1].startswith("scheduledbackup"):
            kube.store["scheduledbackup"] = [o for o in kube.store["scheduledbackup"] if o["metadata"]["name"] != args[2]]

    kube.on_apply_k = apply_k
    kube.hooks.append(delete)
    rc, out = restore(repo, capsys, "--switch")
    assert rc == 0, out
    sbs = [o for o in kube.store["scheduledbackup"] if o["metadata"]["name"] == "shop-orders-db"]
    assert len(sbs) == 1 and sbs[0]["spec"]["cluster"] == {"name": "shop-orders-db-g1"}
