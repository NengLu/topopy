# -*- coding: utf-8 -*-

# network.py
# Jose Vicente Perez Pena
# Dpto. Geodinamica-Universidad de Granada
# 18071 Granada, Spain
# vperez@ugr.es // geolovic@gmail.com
#
# MIT License (see LICENSE file)
# Version: 1.1
# October 1th, 2018
#
# Last modified October 3th, 2018

import numpy as np
from scipy.sparse import csc_matrix
from . import Grid, PRaster
  

class Network(PRaster):

    def __init__(self, dem, flow, threshold=0, thetaref=0.45, winsize=0):
        """
        Class to manipulate cells from a Network, which is defined by applying
        a threshold to a flow accumulation raster derived from a topological 
        sorted Flow object.
        
        Parameters:
        -----------
        dem : *topopy.DEM* object
          Digital Elevation Model instance
        flow : *topopy.Flow* object
          Flow direccion instance
        threshold : *int*
          Number the cells to initiate a channel
        thetaref : *float*
          m/n coeficient to calculate chi values in each channel cell
        """
        # Set PRaster properties
        self._size = flow.get_size()
        self._dims = flow.get_dims()
        self._geot = flow.get_geotransform()
        self._cellsize = flow.get_cellsize()
        self._proj = flow.get_projection()
        self._ncells = flow.get_ncells()
      
        # Get a threshold if not specified (0.5% of the total number of cells)
        if threshold == 0:
            threshold = self._ncells * 0.005
            
        # Get sort Nodes for channel cells
        fac = flow.get_flow_accumulation(nodata=False, asgrid=False)
        w = fac > threshold
        w = w.ravel()
        I   = w[flow._ix]
        self._ix  = flow._ix[I]
        self._ixc = flow._ixc[I]
        
        # Get Area, Distance, and Elevations for channel cells
        self._ax = fac.ravel()[self._ix] * self._cellsize**2 # Area in map units
        self._zx = dem.read_array().ravel()[self._ix]
        
        # Distances to mouth (self._dx) and giver-receiver distances (self._dd)
        di = np.zeros(self._ncells)
        self._dd = np.zeros(self._ix.shape) # Giver-Receiver distance
        for n in np.arange(self._ix.size)[::-1]:
            grow, gcol = self.ind_2_cell(self._ix[n])
            rrow, rcol = self.ind_2_cell(self._ixc[n])
            gx, gy = self.cell_2_xy(grow, gcol)
            rx, ry = self.cell_2_xy(rrow, rcol)
            d_gr = np.sqrt((gx - rx)**2 + (gy - ry)**2)
            self._dd[n] = d_gr
            di[self._ix[n]] = di[self._ixc[n]] + d_gr
        self._dx = di[self._ix]
        
        # Get chi values using the input thetaref
        self.calculate_chi(thetaref)
        
        ## TODO

        self._ksn = np.zeros(self._ix.shape)
    
    def calculate_chi(self, thetaref=0.45, a0=1.0):
        """
        Function that calculate chi_values for channel cells
        
        Parameters:
        -----------
        thetaref : *float*
          m/n coeficient to calculate chi
        a0 : *float*
          Reference area to avoid dimensionality (usually don't need to be changed)
        """
        chi = np.zeros(self._ncells)
        for n in np.arange(self._ix.size)[::-1]:
            chi[self._ix[n]] = chi[self._ixc[n]] + (a0 * self._dd[n]/self._ax[n]**thetaref)
            
        self._chi = chi[self._ix]
    
    def get_stream_poi(self, kind="heads", coords="CELL"):
            """
            This function finds points of interest of the drainage network. These points of interest
            can be 'heads', 'confluences' or 'outlets'.
            
            Parameters:
            -----------
            kind : *str* {'heads', 'confluences', 'outlets'}
              Kind of point of interest to return.
            coords : *str* {'CELL', 'XY', 'IND'}
              Output coordinates for the stream point of interest. 
              
            Returns:
            -----------
            numpy.ndarray
              Numpy ndarray with one (id) or two columns ([row, col] or [xi, yi] - depending on coords) 
              with the location of the points of interest 
              
            References:
            -----------
            The algoritms to extract the point of interest have been adapted to Python 
            from Topotoolbox matlab codes developed by Wolfgang Schwanghart (version of 17. 
            August, 2017). These smart algoritms use sparse arrays with giver-receiver indexes, to 
            derive point of interest in a really efficient way. Cite:
                    
            Schwanghart, W., Scherler, D., 2014. Short Communication: TopoToolbox 2 - 
            MATLAB-based software for topographic analysis and modeling in Earth 
            surface sciences. Earth Surf. Dyn. 2, 1–7. https://doi.org/10.5194/esurf-2-1-2014
            """
            # Check input parameters
            if kind not in ['heads', 'confluences', 'outlets']:
                kind = 'heads'
            if coords not in ['CELL', 'XY', 'IND']:
                coords = 'CELL'

            # Get grid channel cells
            w = np.zeros(self._ncells, dtype=np.bool)
            w[self._ix] = True
            w[self._ixc] = True
            
            # Build a sparse array with giver-receivers cells
            aux_vals = np.ones(self._ix.shape, dtype=np.int8)
            sp_arr = csc_matrix((aux_vals, (self._ix, self._ixc)), shape=(self._ncells, self._ncells))
            
            # Get stream POI according the selected type
            if kind == 'heads':
                # Heads will be channel cells marked only as givers (ix) but not as receivers (ixc) 
                sum_arr = np.asarray(np.sum(sp_arr, 0)).ravel()
                out_pos = (sum_arr == 0) & w
            elif kind == 'confluences':
                # Confluences will be channel cells with two or givers
                sum_arr = np.asarray(np.sum(sp_arr, 0)).ravel()
                out_pos = sum_arr > 1
            elif kind == 'outlets':
                # Outlets will be channel cells marked only as receivers (ixc) but not as givers (ix) 
                sum_arr = np.asarray(np.sum(sp_arr, 1)).ravel()
                out_pos = np.logical_and((sum_arr == 0), w)  
                
            out_pos = out_pos.reshape(self._dims)
            row, col = np.where(out_pos)
            
            if coords=="CELL":
                return np.array((row, col)).T
            elif coords=="XY":
                xi, yi = self.cell_2_xy(row, col)
                return np.array((xi, yi)).T
            elif coords=="IND":
                return self.cell_2_ind(row, col)

    def snap_points(self, input_points, kind="channel"):
        """
        Snap input points to channel cells or to stream POI
        
        Parameters:
        ===========
        array : *iterable*
          List/tuple with (x, y) coordinates for the point, or 2-D numpy.ndarray
          with [x, y] columns. 
        kind : *str* {'channel', 'heads', 'confluences', 'outlets'}  
            Kind of point to snap input points
        
        Returns:
        ===========
        numpy.ndarray
          Numpy ndarray with two columns [xi, yi] with the snap points
        """
        if kind not in  ['channel', 'heads', 'confluences', 'outlets']:
            kind = 'channel'
        
        # Extract a numpy array with the coordinate to snap the points
        if kind in ['heads', 'confluences', 'outlets']:
            poi = self.get_stream_poi(kind, "XY")     
        else:
            row, col = self.ind_2_cell(self._ix)
            x, y = self.cell_2_xy(row, col)
            poi = np.array((x, y)).T
        
        # Get array reshaped for the calculation
        xi = input_points[:, 0].reshape((input_points.shape[0], 1))
        yi = input_points[:, 1].reshape((input_points.shape[0], 1))
        xci = poi[:, 0].reshape((1, poi.shape[0]))
        yci = poi[:, 1].reshape((1, poi.shape[0]))
        
        # Calculate distances and get minimum
        di = np.sqrt((xi - xci)**2 + (yi - yci)**2 )
        pos = np.argmin(di, axis=1)
        
        return poi[pos]
    
    def calculate_slope(self, npoints):
        # Get ixcix auxiliar array
        ixcix = np.zeros(self._ncells, np.int)
        ixcix[self._ix] = np.arange(self._ix.size)
        
        # Get heads and sorted them by elevation
        heads = self.get_stream_poi("heads", "IND")
        elev = self._zx[ixcix[heads]]
        spos = np.argsort(-elev)
        heads = heads[spos]
        winlen = npoints * 2 + 1
        slopes = np.zeros(self._ncells)
        r2 = np.zeros(self._ncells)
        
        # Taking sequentally all the heads and compute downstream flow
        for head in heads:
            processing = True
            lcell = head
            mcell = self._ixc[ixcix[head]]
            fcell = self._ixc[ixcix[mcell]]
        
            if ixcix[fcell] == 0 or ixcix[self._ixc[ixcix[fcell]]] == 0:
                continue
            
            # Obtenemos datos de elevacion y distancias
            win = [fcell, mcell, lcell]
            zi = self._zx[ixcix[win]]
            di = self._dx[ixcix[win]]
            
            # Calculamos pendientes
            poli, SCR = np.polyfit(di, zi, deg = 1, full = True)[:2]
            R2 = float(1 - SCR/(zi.size * zi.var()))
            slp = poli[0]
            slopes[mcell] = slp
            r2[mcell] = R2
            
            while processing:
                # Cogemos la siguiente celda del canal (next_cell)
                fcell = win[0]
                next_cell = self._ixc[ixcix[fcell]]
                
                # Comprobamos la siguiente celda del canal
                # Si la siguiente celda del canal no es cero
                if ixcix[next_cell] != 0:
                    # Añadimos siguiente celda
                    win.insert(0, next_cell)
                    fcell = win[0]
                    # Movemos celda central
                    mcell = self._ixc[ixcix[mcell]]
        
                    if len(win) < winlen:
                        # Si estamos al principio del canal, win crece
                        next_cell = self._ixc[ixcix[fcell]]
                        win.insert(0, next_cell)
                        fcell = win[0]
                    else:
                        # Si no estamos al principio, eliminamos celda final
                        win.pop()
                # Si la siguiente celda es cero, no añadimos celdas, sino que win decrece
                else:
                    mcell = self._ixc[ixcix[mcell]]
                    win.pop()
                    win.pop()
                    if len(win) == 3:
                        processing = False
                        slopes[fcell] = 0.00001
                        r2[fcell] = 0.00001
                        
                # Obtenemos datos de elevacion y distancias
                zi = self._zx[ixcix[win]]
                di = self._dx[ixcix[win]]
                
                # Calculamos pendiente de celda central
                poli, SCR = np.polyfit(di, zi, deg = 1, full = True)[:2]
                R2 = float(1 - SCR/(zi.size * zi.var()))
                slp = poli[0]
                
                    
                if slopes[mcell] == 0:
                    slopes[mcell] = slp
                    r2[mcell] = R2
                else:
                    processing = False
        
        self._slp = slopes[self._ix]
    
    ### ^^^^ UP HERE ALL FUNCTIONS TESTED ^^^^

    def get_streams(self, asgrid=True):
        """
        This function extract a drainage network by using a determined area threshold

        Parameters:
        ===========
        asgrid : *bool*
          Indicates if the network is returned as topopy.Grid (True) or as a numpy.array
        """
        # Get grid channel cells
        w = np.zeros(self._ncells, dtype=np.int8)
        w[self._chcells] = 1
        w = w.reshape(self._dims)
        # Return grid
        if asgrid:
            return self._create_output_grid(w, 0)
        else:
            return w
    
    def get_stream_segments(self, asgrid=True):
        """
        This function extract a drainage network by using a determined area threshold
        and output the numerated stream segments.

        Parameters:
        ===========
        asgrid : *bool*
          Indicates if the network is returned as topopy.Grid (True) or as a numpy.array
        """
        # Get heads adn confluences and merge them
        head_ind = self.get_stream_poi("heads", "IND")
        conf_ind = self.get_stream_poi("confluences", "IND")
        all_ind = np.append(head_ind, conf_ind)
        del conf_ind, head_ind # Clean up
        
        # We created a zeros arrays and put in confuences and heads their id
        # Those id will be consecutive numbers starting in one
        seg_arr = np.zeros(self._ncells, dtype=np.int32)
        for n, inds in enumerate(all_ind):
            seg_arr[inds] = n+1
        
        # Move throught giver list. If receiver is 0, give the same id that giver.
        # If a receiver is not 0, that means that we are in a confluence. 
        for n in range(len(self._ix)):
            if seg_arr[self._ixc[n]] == 0:
                seg_arr[self._ixc[n]] = seg_arr[self._ix[n]]
        
        # Reshape and output
        seg_arr = seg_arr.reshape(self._dims)
        if asgrid:
            return self._create_output_grid(seg_arr, 0)
        else:
            return seg_arr

    def get_stream_order(self, kind="strahler", asgrid=True):
        """
        This function extract streams orderded by strahler or shreeve
    
        Parameters:
        ===========
        kind : *str* {'strahler', 'shreeve'}
        asgrid : *bool*
          Indicates if the network is returned as topopy.Grid (True) or as a numpy.array
        """
        if kind not in ['strahler', 'shreeve']:
            return
        
        # Get grid channel cells
        str_ord = np.zeros(self._ncells, dtype=np.int8)
        str_ord[self._chcells] = 1
        visited = np.zeros(self._ncells, dtype=np.int8)
    
        if kind == 'strahler':
            for n in range(len(self._ix)):
                if (str_ord[self._ixc[n]] == str_ord[self._ix[n]]) & visited[self._ixc[n]]:
                    str_ord[self._ixc[n]] = str_ord[self._ixc[n]] + 1                
                else:
                    str_ord[self._ixc[n]] = max(str_ord[self._ix[n]], str_ord[self._ixc[n]])
                    visited[self._ixc[n]] = True
        elif kind == 'shreeve':
            for n in range(len(self._ix)):
                if visited[self._ixc[n]]:
                    str_ord[self._ixc[n]] = str_ord[self._ixc[n]] + str_ord[self._ix[n]]
                else:
                    str_ord[self._ixc[n]] = max(str_ord[self._ix[n]], str_ord[self._ixc[n]])
                    visited[self._ixc[n]] = True
        str_ord = str_ord.reshape(self._dims)
        
        if asgrid:
            return self._create_output_grid(str_ord, nodata_value=0)
        else:
            return str_ord
    
    def get_main_channels(self, heads=None):
        # Aceptar salida a vector
        pass
    
    
    def _create_output_grid(self, array, nodata_value=None):
        """
        Convenience function that creates a Grid object from an input array. The array
        must have the same shape that self._dims and will maintain the Flow object 
        properties as dimensions, geotransform, reference system, etc.
        
        Parameters:
        ===========
        array : *numpy.ndarray*
          Array to convert to a Grid object
        nodata_value _ *int* / *float*
          Value for NoData values
          
        Returns:
        ========
        Grid object with the same properties that Flow
        """
        grid = Grid()
        grid.copy_layout(self)
        grid._nodata = nodata_value
        grid._array = array
        grid._tipo = str(array.dtype)
        return grid  
    
#    def get_stream_poi(self, threshold, kind="heads"):
#        """
#        This function finds points of interest of the drainage network. These points of interest
#        can be 'heads', 'confluences' or 'outlets'.
#        
#        Parameters:
#        -----------
#        threshold : *int* 
#          Area threshold to initiate a channels (in cells)
#        kind : *str* {'heads', 'confluences', 'outlets'}
#          Kind of point of interest to return. 
#          
#        Returns:
#        -----------
#        (row, col) : *tuple*
#          Tuple of numpy nd arrays with the location of the points of interest
#          
#        References:
#        -----------
#        The algoritms to extract the point of interest have been adapted to Python 
#        from Topotoolbox matlab codes developed by Wolfgang Schwanghart (version of 17. 
#        August, 2017). These smart algoritms use sparse arrays with giver-receiver indexes, to 
#        derive point of interest in a really efficient way. Cite:
#                
#        Schwanghart, W., Scherler, D., 2014. Short Communication: TopoToolbox 2 - 
#        MATLAB-based software for topographic analysis and modeling in Earth 
#        surface sciences. Earth Surf. Dyn. 2, 1–7. https://doi.org/10.5194/esurf-2-1-2014
#        """
#        # Check input parameters
#        if kind not in ['heads', 'confluences', 'outlets']:
#            return np.array([]), np.array([])
#        
#        # Get the Flow Accumulation and select cells that meet the threholds
#        fac = self.flow_accumulation(nodata = False).read_array()
#        w = fac > threshold
#        del fac
#        
#        # Build a sparse array with giver-receivers cells
#        w = w.ravel()
#        I   = w[self._ix]
#        ix  = self._ix[I]
#        ixc = self._ixc[I]
#        aux_vals = np.ones(ix.shape, dtype=np.int8)
#    
#        sp_arr = csc_matrix((aux_vals, (ix, ixc)), shape=(self._ncells, self._ncells))
#        del I, ix, ixc, aux_vals # Clean up (Don't want to leave stuff in memory)
#        
#        if kind == 'heads':
#            # Heads will be channel cells marked only as givers (ix) but not as receivers (ixc) 
#            sum_arr = np.asarray(np.sum(sp_arr, 0)).ravel()
#            out_pos = (sum_arr == 0) & w
#        elif kind == 'confluences':
#            # Confluences will be channel cells with two or givers
#            sum_arr = np.asarray(np.sum(sp_arr, 0)).ravel()
#            out_pos = sum_arr > 1
#        elif kind == 'outlets':
#            # Outlets will be channel cells marked only as receivers (ix) but not as givers (ixc) 
#            sum_arr = np.asarray(np.sum(sp_arr, 1)).ravel()
#            out_pos = (sum_arr == 0) & w  
#            
#        out_pos = out_pos.reshape(self._dims)
#        row, col = np.where(out_pos)
#        
#        return row, col    
#
#    def get_stream_order(self, threshold, kind="strahler", asgrid=True):
#        """
#        This function extract stream orders by using a determined area threshold
#    
#        Parameters:
#        ===========
#        threshold : *int* 
#          Area threshold to initiate a channels (in cells)
#        kind : *str* {'strahler', 'shreeve'}
#        asgrid : *bool*
#          Indicates if the network is returned as topopy.Grid (True) or as a numpy.array
#        """
#        if kind not in ['strahler', 'shreeve']:
#            return
#        
#        fac = self.get_flow_accumulation(nodata=False, asgrid=False)
#        w = fac > threshold
#        w = w.ravel()
#        I   = w[self._ix]
#        ix  = self._ix[I]
#        ixc = self._ixc[I]
#    
#        str_ord = np.copy(w).astype(np.int8)
#        visited = np.zeros(self._ncells, dtype=np.int8)
#    
#        if kind == 'strahler':
#            for n in range(len(ix)):
#                if (str_ord[ixc[n]] == str_ord[ix[n]]) & visited[ixc[n]]:
#                    str_ord[ixc[n]] = str_ord[ixc[n]] + 1
#                else:
#                    str_ord[ixc[n]] = max(str_ord[ix[n]], str_ord[ixc[n]])
#                    visited[ixc[n]] = True
#        elif kind == 'shreeve':
#            for n in range(len(ix)):
#                if visited[ixc[n]]:
#                    str_ord[ixc[n]] = str_ord[ixc[n]] + str_ord[ix[n]]
#                else:
#                    str_ord[ixc[n]] = max(str_ord[ix[n]], str_ord[ixc[n]])
#                    visited[ixc[n]] = True
#        str_ord = str_ord.reshape(self._dims)
#        
#        if asgrid:
#            return self._create_output_grid(str_ord, nodata_value=0)
#        else:
#            return str_ord
#
#    def get_network(self, threshold, asgrid=True):
#        """
#        This function extract a drainage network by using a determined area threshold
#
#        Parameters:
#        ===========
#        threshold : *int* 
#          Area threshold to initiate a channels (in cells)
#        asgrid : *bool*
#          Indicates if the network is returned as topopy.Grid (True) or as a numpy.array
#        """
#        # Get the Flow Accumulation and select cells that meet the threholds
#        fac = self.get_flow_accumulation(nodata = False, asgrid=False)
#        w = fac > threshold
#        w = w.astype(np.int8)
#        if asgrid:
#            return self._create_output_grid(w, 0)
#        else:
#            return w
#        
   
#
#    def _get_presills(self, flats, sills, dem):
#        """
#        This functions extracts the presill pixel locations (i.e. pixelimmediately 
#        upstream to sill pixels)- Adapted from TopoToolbox matlab codes.
#        """
#        zvals = dem.read_array()
#        flats_arr = flats.read_array().astype("bool")
#        dims = zvals.shape
#        row, col = sills.find()
#        
#        rowadd = np.array([-1, -1, 0, 1, 1,  1,  0, -1])
#        coladd = np.array([ 0,  1, 1, 1, 0, -1, -1, -1])
#        ps_rows = np.array([], dtype=np.int32)
#        ps_cols = np.array([], dtype=np.int32)
#        
#        for n in range(8):
#            rowp = row + rowadd[n]
#            colp = col + coladd[n]
#            # Avoid neighbors outside array (remove cells and their neighbors)
#            valid_rc = (rowp >= 0) & (colp >= 0) & (rowp < dims[0]) & (colp < dims[1])
#            rowp = rowp[valid_rc]
#            colp = colp[valid_rc]
#            # Discard cells (row-col pairs) that do not fullfill both conditions
#            cond01 = zvals[row[valid_rc], col[valid_rc]] == zvals[rowp, colp]
#            cond02 = flats_arr[rowp, colp]
#            valid_pix = np.logical_and(cond01, cond02)
#            ps_rows = np.append(ps_rows, rowp[valid_pix])
#            ps_cols = np.append(ps_cols, colp[valid_pix])
#      
#        ps_pos = list(zip(ps_rows, ps_cols))
#        return ps_pos
#       
#    def _get_topodiff(self, topodiff, flats):
#        """
#        This function calculate an auxiliar topography to sort the flats areas
#        """
#        tweight = 2
#        carvemin = 0.1                       
#        struct = np.ones((3, 3), dtype="int8")
#        lbl_arr, nlbl = ndimage.label(flats.read_array(), structure=struct)
#        lbls = np.arange(1, nlbl + 1)
#        
#        for lbl in lbls:
#            topodiff[lbl_arr == lbl] = (topodiff[lbl_arr==lbl].max() - topodiff[lbl_arr == lbl])**tweight + carvemin
#                    
#        return topodiff
#    
#    def _get_weights(self, flats, topodiff, ps_pos):
#        """
#        This function calculate weights in the flats areas by doing a cost-distance analysis.
#        It uses presill positions as seed locations, and an auxiliar topography as friction
#        surface.
#        """
#        flats_arr = flats.read_array().astype("bool")
#        flats_arr = np.invert(flats_arr)
#        topodiff[flats_arr] = 99999
#        if len(ps_pos) > 0:
#            lg = graph.MCP_Geometric(topodiff)
#            topodiff = lg.find_costs(starts=ps_pos)[0] + 1
#        topodiff[flats_arr] = -99999
#        
#        return topodiff
#    
#    def _sort_pixels(self, dem, weights):
#        """
#        Sort the cells of a DEM in descending order. It uses weights for the flats areas
#        """
#        # Sort the flat areas
#        rdem = dem.read_array().ravel()
#        rweights = weights.ravel()
#        ix_flats = np.argsort(-rweights, kind='quicksort')
#        
#        # Sort the rest of the pixels from the DEM
#        ndx = np.arange(self._ncells, dtype=np.int)
#        ndx = ndx[ix_flats]
#        ix = ndx[np.argsort(-rdem[ndx], kind='mergesort')]
#        
#        return ix
#    
#    def _get_receivers(self, ix, dem):
#        
#        dem = dem.read_array()
#        rdem = dem.ravel()
#        
#        pp = np.zeros(self._dims, dtype=np.int32)
#        IX = np.arange(self._ncells, dtype=np.int32)
#        pp = pp.ravel()
#        pp[ix] = IX
#        pp = pp.reshape(self._dims)
#                
#        # Get cardinal neighbors
#        footprint= np.array([[0, 1, 0],
#                             [1, 1, 1],
#                             [0, 1, 0]], dtype=np.int)
#        IXC1 = ndimage.morphology.grey_dilation(pp, footprint=footprint)
#        xxx1 = np.copy(IXC1)
#        IX = IXC1.ravel()[ix]
#        IXC1 = ix[IX]
#        G1   = (rdem[ix]-rdem[IXC1])/(self._cellsize)
#        
#        # Get diagonal neighbors
#        footprint= np.array([[1, 0, 1],
#                             [0, 1, 0],
#                             [1, 0, 1]], dtype=np.int)
#        IXC2 = ndimage.morphology.grey_dilation(pp, footprint=footprint)
#        xxx2 = np.copy(IXC2)
#        IX = IXC2.ravel()[ix]
#        IXC2 = ix[IX]
#        G2   = (rdem[ix]-rdem[IXC2])/(self._cellsize * np.sqrt(2))
#        
#        del IX
#        
#        # Get the steepest one
#        I  = (G1<=G2) & (xxx2.ravel()[ix]>xxx1.ravel()[ix])
#        ixc = IXC1
#        ixc[I] = IXC2[I]
#        
#        return ixc
class FlowError(Exception):
    pass