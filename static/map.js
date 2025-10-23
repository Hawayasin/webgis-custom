// Initialize map
var map = L.map('map').setView([-7.799336787432816, 110.36849231787359], 11);

// Add OpenStreetMap base layer
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '© OpenStreetMap contributors'
}).addTo(map);

// Create feature group for drawn items
var drawnItems = new L.FeatureGroup();
map.addLayer(drawnItems);

// Initialize draw control with marker, line, and polygon options
var drawControl = new L.Control.Draw({
    draw: {
        marker: true,
        polyline: true,
        polygon: true,
        rectangle: false,
        circle: false,
        circlemarker: false
    },
    edit: {
        featureGroup: drawnItems,
        remove: true
    }
});
map.addControl(drawControl);

// Add drawn items to the map
map.on('draw:created', function(e) {
    var layer = e.layer;
    drawnItems.addLayer(layer);
});

// Calculate geometry function
document.getElementById('calculate-geometry').addEventListener('click', function() {
    var results = [];
    
    drawnItems.eachLayer(function(layer) {
        var geojson = layer.toGeoJSON();
        var result = {
            type: geojson.geometry.type
        };

        // Calculate area for polygons
        if (geojson.geometry.type === 'Polygon') {
            var area = turf.area(geojson);
            result.area = Math.round(area * 100) / 100; // Round to 2 decimal places
            result.areaKm = Math.round(area / 1000000 * 100) / 100; // Convert to km²
        }
        
        // Calculate length for lines
        if (geojson.geometry.type === 'LineString') {
            var length = turf.length(geojson, {units: 'kilometers'});
            result.length = Math.round(length * 100) / 100; // Round to 2 decimal places
        }

        results.push(result);
    });

    // Create result message
    var message = 'Calculate Area:\n\n';
    results.forEach((result, index) => {
        message += `Feature ${index + 1} (${result.type}):\n`;
        if (result.area !== undefined) {
            message += `Luas: ${result.area} m² (${result.areaKm} km²)\n`;
        }
        if (result.length !== undefined) {
            message += `Panjang: ${result.length} km\n`;
        }
        message += '\n';
    });

    if (results.length === 0) {
        message = 'No features found. Draw some features first!';
    }

    alert(message);
});
//       headers: { 'Content-Type': 'application/json' },
//       body: JSON.stringify(geojson)
//     })
//     .then(res => res.text())
//     .then(msg => alert(msg))
//     .catch(err => alert('Error: ' + err));
//   }
// });

// Utility: convert Leaflet layer to GeoJSON feature
function layerToFeature(layer) {
  return layer.toGeoJSON();
}

// Operation: intersect two selected features
function doIntersect() {
  if (selectedFeatures.length < 2) { alert('Pilih minimal dua fitur untuk intersect'); return; }
  var f1 = layerToFeature(selectedFeatures[0].layer);
  var f2 = layerToFeature(selectedFeatures[1].layer);
  var result = turf.intersect(f1, f2);
  if (!result) { alert('Tidak ada irisan antara kedua fitur'); return; }
  showResult(result, 'Intersect result');
}

// Operation: clip (mask) - keep area of source within mask
function doClip() {
  if (selectedFeatures.length < 2) { alert('Pilih fitur sumber dan mask (dua fitur)'); return; }
  var source = layerToFeature(selectedFeatures[0].layer);
  var mask = layerToFeature(selectedFeatures[1].layer);
  var result = turf.intersect(source, mask);
  if (!result) { alert('Hasil clip kosong'); return; }
  showResult(result, 'Clip result');
}

// Operation: dissolve - merge selected polygon features
function doDissolve() {
  if (selectedFeatures.length < 1) { alert('Pilih setidaknya satu fitur untuk dissolve'); return; }
  var feats = selectedFeatures.map(f => layerToFeature(f.layer));
  // convert MultiFeature to FeatureCollection
  var fc = turf.featureCollection(feats.map(f => f.type === 'Feature' ? f : turf.feature(f.geometry, f.properties)));
  // union iteratively
  var unioned = fc.features[0];
  for (var i = 1; i < fc.features.length; i++) {
    unioned = turf.union(unioned, fc.features[i]);
  }
  showResult(unioned, 'Dissolve result');
}

// Show result on map and optionally allow saving
function showResult(feature, title) {
  var layer = L.geoJSON(feature, {
    style: { color: '#00ff00' }
  }).addTo(map);
  map.fitBounds(layer.getBounds());
  // set as temporary selected
  selectedFeatures = [{ id: L.stamp(layer), layer: layer }];
  // attach popup with save option
  layer.bindPopup(`<b>${title}</b><br><button id="save-result">Simpan ke PostGIS</button>`).openPopup();
  // attach click listener for save button
  setTimeout(() => {
    var btn = document.getElementById('save-result');
    if (btn) btn.addEventListener('click', function () {
      var geojson = feature.type === 'Feature' ? feature : turf.feature(feature.geometry, feature.properties || {});
      geojson.properties = geojson.properties || {};
      var nama = prompt('Nama untuk fitur hasil:', title);
      if (nama !== null) {
        geojson.properties.nama = nama;
        fetch('/add_feature', {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(geojson)
        })
        .then(res => res.text()).then(msg => alert(msg)).catch(err => alert('Error: ' + err));
      }
    });
  }, 500);
}

// Save selected layers individually
function saveSelected() {
  if (selectedFeatures.length < 1) { alert('Tidak ada fitur terpilih'); return; }
  selectedFeatures.forEach(s => {
    var geojson = layerToFeature(s.layer);
    geojson.properties = geojson.properties || {};
    var nama = prompt('Nama fitur (optional):', geojson.properties.nama || 'Fitur');
    if (nama !== null) {
      geojson.properties.nama = nama;
      fetch('/add_feature', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(geojson) })
        .then(res => res.text()).then(msg => alert(msg)).catch(err => alert('Error: ' + err));
    }
  });
}

// Hook up buttons
document.addEventListener('click', function (e) {
  if (!e.target) return;
  if (e.target.id === 'btn-intersect') doIntersect();
  if (e.target.id === 'btn-clip') doClip();
  if (e.target.id === 'btn-dissolve') doDissolve();
  if (e.target.id === 'btn-save') saveSelected();
});

// Expose some utilities for debugging
window._drawnItems = drawnItems;
window._postgisLayer = postgisLayer;
window._selectedFeatures = selectedFeatures;
