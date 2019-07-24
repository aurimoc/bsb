from .statistics import Statistics
from .plotting import plotNetwork
import numpy as np
import h5py
from pprint import pprint

###############################
## Scaffold class
#    * Bootstraps configuration
#    * Loads geometries, morphologies, ...
#    * Creates network architecture
#    * Sets up simulation

class Scaffold:

	def __init__(self, config):
		self.configuration = config
		self.resetNetworkCache()
		# Debug statistics, unused.
		self.statistics = Statistics(self)
		self._nextId = 0
		# Use the configuration to initialise all components such as cells and layers
		# to prepare for the network architecture compilation.
		self.initialiseComponents()
		# Code to be compliant with old code, to be removed after rework
		self.initLegacyCode()

	def initialiseComponents(self):
		# Initialise the components now that the scaffoldInstance is available
		self._initialiselayers()
		self._initialise_cells()
		self._initialisePlacementStrategies()

	def _initialise_cells(self):
		for name, cell_type in self.configuration.cell_types.items():
			cell_type.initialise(self)

	def _initialiselayers(self):
		for name, layer in self.configuration.layers.items():
			layer.initialise(self)

	def _initialisePlacementStrategies(self):
		for name, placement in self.configuration.PlacementStrategies.items():
			placement.initialise(self)

	def compileNetworkArchitecture(self):
		# Place the cells starting from the lowest density celltypes.
		cell_types = sorted(self.configuration.cell_types.values(), key=lambda x: x.density)
		for cell_type in cell_types:
			cell_type.placement.place(cell_type)

		self.save()
		plotNetwork(self, from_memory=True)

	def resetNetworkCache(self):
		# Cell positions dictionary per cell type. Columns: X, Y, Z.
		self.cells_by_type = {key: np.empty((0, 3)) for key in self.configuration.cell_types.keys()}
		# Cell positions dictionary per layer. Columns: Type, X, Y, Z.
		self.cells_by_layer = {key: np.empty((0, 4)) for key in self.configuration.layers.keys()}
		# Cell positions dictionary. Columns: Cell ID, Type, X, Y, Z.
		self.cells = np.empty((0, 5))

	def place_cells(self, cell_type, layer, positions):
		# Store cells per type as X, Y, Z
		self.cells_by_type[cell_type.name] = np.concatenate((
			self.cells_by_type[cell_type.name],
			positions
		))
		# Store cells per layer as typeID, X, Y, Z
		positionsWithTypeId = np.column_stack((
			np.ones(positions.shape[0]) * cell_type.id,
			positions
		))
		self.cells_by_layer[layer.name] = np.concatenate((
			self.cells_by_layer[layer.name],
			positionsWithTypeId
		))
		# Ask the scaffold for an ID per cell, thread safe?
		CellIDs = self.allocateIDs(positions.shape[0])
		# Store cells as ID, typeID, X, Y, Z
		positionsWithIdAndTypeId = np.column_stack((
			CellIDs,
			positionsWithTypeId
		))
		self.cells = np.concatenate((
			self.cells,
			positionsWithIdAndTypeId
		))

	def allocateIDs(self, count):
		IDs = np.array(range(self._nextId, self._nextId + count))
		self._nextId += count
		return IDs

	def save(self):
		f = h5py.File('scaffold_new_test.hdf5', 'w')
		cell_typeIDs = self.configuration.CellTypeIDs
		dset = f.create_dataset('positions', data=self.cells)
		dset.attrs['types'] = cell_typeIDs
		f.close()


	def initLegacyCode(self):
		self.placement_stats = {key: {} for key in self.configuration.cell_types.keys()}
		for key, subdic in self.placement_stats.items():
			subdic['number_of_cells'] = []
			subdic['total_n_{}'.format(key)] = 0
			if key != 'purkinje':
				subdic['{}_subl'.format(key)] = 0
