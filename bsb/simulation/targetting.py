import random, numpy as np
from ..exceptions import *
from itertools import chain


class TargetsNeurons:
    def initialise(self, scaffold):
        super().initialise(scaffold)
        # Set targetting method
        get_targets_name = "_targets_" + self.targetting
        method = (
            getattr(self, get_targets_name) if hasattr(self, get_targets_name) else None
        )
        if not callable(method):
            raise NotImplementedError(
                "Unimplemented neuron targetting type '{}' in {}".format(
                    self.targetting, self.node_name
                )
            )
        self._get_targets = method

    def _targets_local(self):
        """
        Target all or certain cells in a spherical location.
        """
        # Compile a list of the cells and build a compound tree.
        target_cells = np.empty((0, 3))
        id_map = np.empty(0)
        for t in self.cell_types:
            pos = self.scaffold.get_placement_set(t).positions
            target_cells = np.vstack((target_cells, pos))
            id_map = np.concatenate((id_map, cells[:, 0]))
        tree = KDTree(target_cells)
        # Query the tree for all the targets
        target_ids = tree.query_radius([self.origin], self.radius)[0]
        return id_map[target_ids].astype(int).tolist()

    def _targets_cylinder(self):
        """
        Target all or certain cells within a cylinder of specified radius.
        """
        # Compile a list of the cells.

        if self.cell_types == ["mossy_fibers"]:
            target_cells = np.empty((0, 2))
            id_map = np.empty(0)

            ps = self.scaffold.get_placement_set("glomerulus")
            pos = ps.positions[:, [0, 2]]
            target_cells = np.vstack((target_cells, pos))
            id_map = np.concatenate((id_map, ps.identifiers))

            if not hasattr(self, "origin"):
                x = self.scaffold.configuration.X
                z = self.scaffold.configuration.Z
                origin = np.array((x, z))
            else:
                origin = np.array(self.origin)
            # Find cells falling into the cylinder volume
            in_range_mask = (
                np.sum((target_cells[:, [0, 1]] - origin) ** 2, axis=1) < self.radius ** 2
            )

            id_map_glom = id_map[in_range_mask].astype(int).tolist()
            conn_glom_mf = self.scaffold.get_connectivity_set("mossy_to_glomerulus")
            ids_glom_all = conn_glom_mf.to_identifiers
            ids_mf_all = conn_glom_mf.from_identifiers
            mf_ids = []
            for id in range(len(ids_glom_all)):
                if ids_glom_all[id] in id_map_glom:
                    mf_ids.append(ids_mf_all[id])
            mf_ids = np.unique(mf_ids)
            return mf_ids

        else:
            target_cells = np.empty((0, 2))
            id_map = np.empty(0)
            for t in self.cell_types:
                ps = self.scaffold.get_placement_set(t)
                # TODO: Cylinders in other planes than the XZ plane
                pos = ps.positions[:, [0, 2]]
                target_cells = np.vstack((target_cells, pos))
                id_map = np.concatenate((id_map, ps.identifiers))

            if not hasattr(self, "origin"):
                x = self.scaffold.configuration.X
                z = self.scaffold.configuration.Z
                origin = np.array((x, z))
            else:
                origin = np.array(self.origin)
            # Find cells falling into the cylinder volume
            in_range_mask = (
                np.sum((target_cells[:, [0, 1]] - origin) ** 2, axis=1) < self.radius ** 2
            )
            return id_map[in_range_mask].astype(int).tolist()

    def _targets_cell_type(self):
        """
        Target all cells of certain cell types
        """
        ids = np.concatenate(
            tuple(self.scaffold.get_placement_set(t).identifiers for t in self.cell_types)
        )
        n = len(ids)
        # Use the `cell_fraction` or `cell_count` attribute to determine what portion of
        # the selected ids to exclude.
        if n != 0:
            r_threshold = getattr(
                self, "cell_fraction", getattr(self, "cell_count", n) / n
            )
            if r_threshold == 1:
                return ids
            elif r_threshold == 0:
                return np.empty(0)
            else:
                return ids[np.random.random_sample(n) <= r_threshold]
        else:
            return np.empty(0)

    def _targets_representatives(self):
        target_types = [
            cell_model.cell_type
            for cell_model in self.adapter.cell_models.values()
            if not cell_model.cell_type.relay
        ]
        if hasattr(self, "cell_types"):
            target_types = list(filter(lambda c: c.name in self.cell_types, target_types))
        target_ids = [
            cell_type.get_placement_set().identifiers for cell_type in target_types
        ]
        representatives = [
            random.choice(type_ids) for type_ids in target_ids if len(target_ids) > 0
        ]
        return representatives

    def _targets_by_id(self):
        return self.targets

    def _targets_by_label(self):
        frac = getattr(self, "cell_fraction", None)
        count = getattr(self, "cell_count", None)
        all_labels = chain(*map(self.scaffold.get_labels, self.labels))
        targets = []
        for label in all_labels:
            labelled = self.scaffold.labels[label]
            total = len(labelled)
            if frac is not None:
                n = np.ceil(frac * total)
            elif count is not None:
                n = count
            else:
                n = total
            n = max(0, min(n, total))
            targets.extend(random.sample(list(labelled), n))
        return targets

    def get_targets(self):
        """
        Return the targets of the device.
        """
        if hasattr(self, "_targets"):
            return self._targets
        raise ParallelIntegrityError(
            f"MPI process %rank% failed a checkpoint."
            + " `initialise_targets` should always be called before `get_targets` on all MPI processes.",
            self.adapter.get_rank(),
        )

    def get_patterns(self):
        """
        Return the patterns of the device.
        """
        if hasattr(self, "_patterns"):
            return self._patterns
        raise ParallelIntegrityError(
            f"MPI process %rank% failed a checkpoint."
            + " `initialise_patterns` should always be called before `get_patterns` on all MPI processes.",
            self.adapter.get_rank(),
        )

    def initialise_targets(self):
        if self.adapter.get_rank() == 0:
            targets = self._get_targets()
        else:
            targets = None
        # Broadcast to make sure all the nodes have the same targets for each device.
        self._targets = self.scaffold.MPI.COMM_WORLD.bcast(targets, root=0)

    def initialise_patterns(self):
        if self.adapter.get_rank() == 0:
            # Have root 0 prepare the possibly random patterns.
            patterns = self.create_patterns()
        else:
            patterns = None
        # Broadcast to make sure all the nodes have the same patterns for each device.
        self._patterns = self.scaffold.MPI.COMM_WORLD.bcast(patterns, root=0)

    # Define new targetting methods above this line or they will not be registered.
    neuron_targetting_types = [s[9:] for s in vars().keys() if s.startswith("_targets_")]


class TargetsSections:
    def target_section(self, cell):
        if not hasattr(self, "section_targetting"):
            self.section_targetting = "default"
        method_name = "_section_target_" + self.section_targetting
        if not hasattr(self, method_name):
            raise Exception(
                "Unknown section targetting type '{}'".format(self.section_targetting)
            )
        return getattr(self, method_name)(cell)

    def _section_target_default(self, cell):
        if not hasattr(self, "section_count"):
            self.section_count = "all"
        elif self.section_count != "all":
            self.section_count = int(self.section_count)
        sections = cell.sections
        if hasattr(self, "section_types"):
            ts = self.section_types
            sections = [s for s in sections if any(t in s.labels for t in ts)]
        if hasattr(self, "section_type"):
            raise ConfigurationError(
                "`section_type` is deprecated, use `section_types` instead."
            )
        if self.section_count == "all":
            return sections
        return [random.choice(sections) for _ in range(self.section_count)]
