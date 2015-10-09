#!/usr/bin/python
import datetime
import json
import sys
import os


from flask import Flask
from flask import request
from flask.ext.cors import CORS, cross_origin




app = Flask(__name__)
cors = CORS(app)
app.config['CORS_HEADERS'] = 'Content-Type'
# usage: QuadTreeSearch <year>
_proc_status = '/proc/%d/status' % os.getpid()

_scale = {'kB': 1024.0, 'mB': 1024.0*1024.0,
          'KB': 1024.0, 'MB': 1024.0*1024.0}

def _VmB(VmKey):
    '''Private.
    '''
    global _proc_status, _scale
     # get pseudo file  /proc/<pid>/status
    try:
        t = open(_proc_status)
        v = t.read()
        t.close()
    except:
        return 0.0  # non-Linux?
     # get VmKey line e.g. 'VmRSS:  9999  kB\n ...'
    i = v.index(VmKey)
    v = v[i:].split(None, 3)  # whitespace
    if len(v) < 3:
        return 0.0  # invalid format?
     # convert Vm value to bytes
    return float(v[1]) * _scale[v[2]]


def memory(since=0.0):
    '''Return memory usage in bytes.
    '''
    return _VmB('VmSize:') - since


def resident(since=0.0):
    '''Return resident memory usage in bytes.
    '''
    return _VmB('VmRSS:') - since


def stacksize(since=0.0):
    '''Return stack size in bytes.
    '''
    return _VmB('VmStk:') - since



class BBox:
    def __init__(self, maxLat, maxLon, minLat, minLon):
        self.maxLat = maxLat
        self.minLat = minLat
        self.maxLon = maxLon
        self.minLon = minLon
    def containsPoint(self, aPoint):
        return self.minLat <= aPoint[0] and aPoint[0] <= self.maxLat and self.minLon <= aPoint[1] and aPoint[1] <= self.maxLon
    def intersectEmpty(self, aBBox):
        if (self.maxLat < aBBox.minLat): return True
        if (self.minLat > aBBox.maxLat): return True
        if (self.maxLon < aBBox.minLon): return True
        if (self.minLon > aBBox.maxLon): return True
        return False
    def intersect(self, aBBox):
        return BBox(min(self.maxLat, aBBox.maxLat), min(self.maxLon, aBBox.maxLon), max(self.minLat, aBBox.minLat), max(self.minLon, aBBox.minLon))
    def toJSON(self):
        return '{"maxLat":%f, "maxLon":%f, "minLat":%f, "minLon": %f}' % (self.maxLat, self.maxLon, self.minLat, self.minLon)
    def fileHandle(self):
        return '%1.2f_%1.2f_%1.2f_%1.2f' % (self.maxLat, self.maxLon, self.minLat, self.minLon)

def makeBBox(aBBoxDesc):
    return BBox(aBBoxDesc['maxLat'], aBBoxDesc['maxLon'], aBBoxDesc['minLat'], aBBoxDesc['minLon'])

class LeafNode:
    def __init__(self, bbox, fileName):
        self.points = []
        self.bbox = bbox
        self.fileName = fileName
        self.loaded = False
    def findPoints(self, aBBox):
        # print 'Searching leaf ' + self.bbox.toJSON()
        if(not self.loaded):self.load()
        if self.bbox.intersectEmpty(aBBox): return []
        bbox2 = self.bbox.intersect(aBBox)
        # print 'Searching bbox: ' + bbox2.toJSON()
        result =  [point for point in self.points if bbox2.containsPoint(point) ]
        # print 'Result: ' + str(result)
        return result
    def __str__(self):
        return 'LeafNode(' + str(self.points) + ',%f, %f, %f, %f)' % (self.maxLat, self.maxLon, self.minLat, self.minLon)
    def showPoints(self):
        return len(self.points)
    def numPoints(self):
        return len(self.points)
    def addPoint(self, aPoint):
        if (not self.bbox.containsPoint(aPoint)):
            print ('Error: Point (%f, %f) not in leaf with bounding box %s!' % (point[0], point[1], self.bbox.toJSON()))
            return
        self.points.append(aPoint)
    def sanityCheck(self):
        result = True
        for point in self.points:
            if (not self.bbox.containsPoint(point)):
                print ('Point (%f, %f) not in leaf with bounding box %s!' % (point[0], point[1], self.bbox.toJSON()))
                result = False
        return result
    def toJSON(self):
        return '{"bbox":%s, "numPoints[%d]}' % (self.bbox.toJSON(), len(self.points))
    def load(self):
        try:
            file = open(self.fileName, 'r')
            ptStr = file.read()
        except IOError:
            print 'Error reading file ' + self.fileName
            self.points = []
            self.loaded = False
            return
        try:
            self.points = json.loads(ptStr)
        except ValueError:
            self.points = []
        self.loaded = True
    def clear(self):
        self.points = []
        self.loaded = False
    def makeCSVFileName(self):
        return '%s-csv.json' % self.bbox.fileHandle()



class InternalNode:
    def __init__(self, bbox, nwNode, neNode, swNode, seNode):
        self.bbox = bbox
        self.nw = nwNode
        self.ne = neNode
        self.sw = swNode
        self.se = seNode
        self.subTrees = [nwNode, neNode, swNode, seNode]
    def findPoints(self, bbox):
        result = []
        for subTree in self.subTrees:
            if subTree.bbox.intersectEmpty(bbox): continue
            result.extend(subTree.findPoints(subTree.bbox.intersect(bbox)))

        return result
    def showPoints(self):
        return [subTree.showPoints() for subTree in self.subTrees]
    def numPoints(self):
        return sum([subTree.numPoints() for subTree in self.subTrees])
    def addPoint(self, aPoint):
        if (not self.bbox.containsPoint(aPoint)): return
        for subTree in self.subTrees:
            if (subTree.bbox.containsPoint(aPoint)):
                subTree.addPoint(aPoint)
                return
        print('Error: %s contains (%f, %f) but no subtree does' % (self.bbox.toJSON(), aPoint[0], aPoint[1]))
    def sanityCheck(self):
        if (self.nw.bbox.minLat <  self.sw.bbox.minLat):
            print('Error: nw bbox: %s, sw bbox:%s' % (self.nw.toJSON(), self.sw.toJSON()))
            return False
        if (self.ne.bbox.minLat <  self.se.bbox.minLat):
            print('Error: ne bbox: %s, se bbox:%s' % (self.ne.toJSON(), self.se.toJSON()))
            return False
        if (self.ne.bbox.minLon <  self.nw.bbox.minLon):
            print('Error: ne bbox: %s, nw bbox:%s' % (self.ne.toJSON(), self.nw.toJSON()))
            return False
        if (self.se.bbox.minLon <  self.sw.bbox.minLon):
            print('Error: se bbox: %s, sw bbox:%s' % (self.se.toJSON(), self.sw.toJSON()))
            return False
        return reduce(lambda x,y: x and y, [subTree.sanityCheck() for subTree in self.subTrees], True)
    def toJSON(self):
        return '{"bbox":%s, "nw":%s, "ne":%s, "sw": %s, "se":%s, "pts":%d}' % (self.bbox.toJSON(), self.nw.toJSON(), self.ne.toJSON(), self.sw.toJSON(), self.se.toJSON(), self.numPoints())
    def load(self):
        for subTree in self.subTrees: subTree.load()
    def clear(self):
        for subTree in self.subTrees: subTree.clear()

def makeTree(aQTDesc, directory):
    bbox = makeBBox(aQTDesc['bbox'])
    if 'nw' in aQTDesc:
        return InternalNode(bbox, makeTree(aQTDesc['nw'], directory), makeTree(aQTDesc['ne'], directory), makeTree(aQTDesc['sw'], directory), makeTree(aQTDesc['se'], directory))
    else:
        return LeafNode(bbox, '%s/%s' % (directory, aQTDesc['file']))

def readEntry(year, month, res):
    directory = '../db/qTrees/%s_%s_%s'  % (year, month, res)
    f = open('%s/qTree.json' % directory, 'r')
    jstr = f.read()
    qtDesc = json.loads(jstr)
    qt = makeTree(qtDesc, directory)
    qt.sanityCheck()
    f.close()
    return qt



class QtDict:
    def __init__(self):
        self.years = {}
    def ensureEntry(self, year, month):
        if (not year in self.years):
            self.years[year] = {}
        if (not month in self.years[year]):
            self.years[year][month] = {}
    def store(self, year, month, res, qt):
        self.ensureEntry(year, month)
        self.years[year][month][res] = qt
    def hasEntry(self, year, month, res):
        if (not year in self.years): return False
        if (not month in self.years[year]): return False
        return res in self.years[year][month]
    def getQt(self, year, month, res):
        if self.hasEntry(year, month, res):
            return self.years[year][month][res]
        else:
            return None
    def allEntries(self):
        result = []
        for year in self.years:
            for month in self.years[year]:
                for res in self.years[year][month]:
                    result.append({"year": year, "month": month, "res": res})
        return result
    def getEntry(self, year, month, res):
        self.store(year, month, res, readEntry(year, month, res))
    def getMonth(self, year, month):
        resolutions = ['10', '4', '2', '1']
        for res in resolutions:
            self.getEntry(year, month, res)
    def getYear(self, year):
        months = ['01', '02', '03', '04', '05', '06', '07', '08', '09', '10', '11', '12']
        for month in months:
            self.getMonth(year, month)
    def findPoints(self, bbox, year, month, res):
        if self.hasEntry(year, month, res):
            qt = self.getQt(year, month, res)
            a = datetime.datetime.now()
            pts = qt.findPoints(bbox)
            b =  datetime.datetime.now()
            # web.header('Content-Type', 'application/json')
            return "found %d points in %d microseconds\n" % (len(pts), (b - a).microseconds)
        else:
            result = ["no entries for %s/%s at resolution %s" % (month, year, res)]
            result.extend(self.allEntries())
            return ','.join(result) + '\n'
    def allPoints(self, bbox, year, month, res):
        if self.hasEntry(year, month, res):
            qt = self.getQt(year, month, res)
            pts = qt.findPoints(bbox)
            return json.dumps(pts)
        else:
            return json.dumps([])
    def setup(self):
        for year in range(1998, 2015):
            self.getYear(str(year))
        for month in ['09', '10', '11', '12']:
            self.getMonth('1997', month)
        self.getMonth('2015', '01')
        res_1 = filter(lambda x: x['res'] == '1', qtDict.allEntries())
        for record in res_1:
            qt = self.getQt(record['year'], record['month'], record['res'])
            qt.load()
    def clear(self):
        for entry in self.allEntries():
            if (entry['res'] == '1'): continue
            qt = self.getQt(entry['year'], entry['month'], entry['res'])
            qt.clear()


qtDict = QtDict()
qtDict.setup()
#
# Color values for the table
#
def rgb(r, g, b):
    return "#%02X%02X%02X" % (r, g, b)
colorValues = [rgb(59,76,192),
    rgb(60,78,194),
    rgb(61,80,195),
    rgb(62,81,197),
    rgb(63,83,198),
    rgb(64,85,200),
    rgb(66,87,201),
    rgb(67,88,203),
    rgb(68,90,204),
    rgb(69,92,206),
    rgb(70,93,207),
    rgb(71,95,209),
    rgb(73,97,210),
    rgb(74,99,211),
    rgb(75,100,213),
    rgb(76,102,214),
    rgb(77,104,215),
    rgb(79,105,217),
    rgb(80,107,218),
    rgb(81,109,219),
    rgb(82,110,221),
    rgb(84,112,222),
    rgb(85,114,223),
    rgb(86,115,224),
    rgb(87,117,225),
    rgb(89,119,226),
    rgb(90,120,228),
    rgb(91,122,229),
    rgb(93,123,230),
    rgb(94,125,231),
    rgb(95,127,232),
    rgb(96,128,233),
    rgb(98,130,234),
    rgb(99,131,235),
    rgb(100,133,236),
    rgb(102,135,237),
    rgb(103,136,238),
    rgb(104,138,239),
    rgb(106,139,239),
    rgb(107,141,240),
    rgb(108,142,241),
    rgb(110,144,242),
    rgb(111,145,243),
    rgb(112,147,243),
    rgb(114,148,244),
    rgb(115,150,245),
    rgb(116,151,246),
    rgb(118,153,246),
    rgb(119,154,247),
    rgb(120,156,247),
    rgb(122,157,248),
    rgb(123,158,249),
    rgb(124,160,249),
    rgb(126,161,250),
    rgb(127,163,250),
    rgb(129,164,251),
    rgb(130,165,251),
    rgb(131,167,252),
    rgb(133,168,252),
    rgb(134,169,252),
    rgb(135,171,253),
    rgb(137,172,253),
    rgb(138,173,253),
    rgb(140,174,254),
    rgb(141,176,254),
    rgb(142,177,254),
    rgb(144,178,254),
    rgb(145,179,254),
    rgb(147,181,255),
    rgb(148,182,255),
    rgb(149,183,255),
    rgb(151,184,255),
    rgb(152,185,255),
    rgb(153,186,255),
    rgb(155,187,255),
    rgb(156,188,255),
    rgb(158,190,255),
    rgb(159,191,255),
    rgb(160,192,255),
    rgb(162,193,255),
    rgb(163,194,255),
    rgb(164,195,254),
    rgb(166,196,254),
    rgb(167,197,254),
    rgb(168,198,254),
    rgb(170,199,253),
    rgb(171,199,253),
    rgb(172,200,253),
    rgb(174,201,253),
    rgb(175,202,252),
    rgb(176,203,252),
    rgb(178,204,251),
    rgb(179,205,251),
    rgb(180,205,251),
    rgb(182,206,250),
    rgb(183,207,250),
    rgb(184,208,249),
    rgb(185,208,248),
    rgb(187,209,248),
    rgb(188,210,247),
    rgb(189,210,247),
    rgb(190,211,246),
    rgb(192,212,245),
    rgb(193,212,245),
    rgb(194,213,244),
    rgb(195,213,243),
    rgb(197,214,243),
    rgb(198,214,242),
    rgb(199,215,241),
    rgb(200,215,240),
    rgb(201,216,239),
    rgb(203,216,238),
    rgb(204,217,238),
    rgb(205,217,237),
    rgb(206,217,236),
    rgb(207,218,235),
    rgb(208,218,234),
    rgb(209,219,233),
    rgb(210,219,232),
    rgb(211,219,231),
    rgb(213,219,230),
    rgb(214,220,229),
    rgb(215,220,228),
    rgb(216,220,227),
    rgb(217,220,225),
    rgb(218,220,224),
    rgb(219,220,223),
    rgb(220,221,222),
    rgb(221,221,221),
    rgb(222,220,219),
    rgb(223,220,218),
    rgb(224,219,216),
    rgb(225,219,215),
    rgb(226,218,214),
    rgb(227,218,212),
    rgb(228,217,211),
    rgb(229,216,209),
    rgb(230,216,208),
    rgb(231,215,206),
    rgb(232,215,205),
    rgb(232,214,203),
    rgb(233,213,202),
    rgb(234,212,200),
    rgb(235,212,199),
    rgb(236,211,197),
    rgb(236,210,196),
    rgb(237,209,194),
    rgb(238,209,193),
    rgb(238,208,191),
    rgb(239,207,190),
    rgb(240,206,188),
    rgb(240,205,187),
    rgb(241,204,185),
    rgb(241,203,184),
    rgb(242,202,182),
    rgb(242,201,181),
    rgb(243,200,179),
    rgb(243,199,178),
    rgb(244,198,176),
    rgb(244,197,174),
    rgb(245,196,173),
    rgb(245,195,171),
    rgb(245,194,170),
    rgb(245,193,168),
    rgb(246,192,167),
    rgb(246,191,165),
    rgb(246,190,163),
    rgb(246,188,162),
    rgb(247,187,160),
    rgb(247,186,159),
    rgb(247,185,157),
    rgb(247,184,156),
    rgb(247,182,154),
    rgb(247,181,152),
    rgb(247,180,151),
    rgb(247,178,149),
    rgb(247,177,148),
    rgb(247,176,146),
    rgb(247,174,145),
    rgb(247,173,143),
    rgb(247,172,141),
    rgb(247,170,140),
    rgb(247,169,138),
    rgb(247,167,137),
    rgb(247,166,135),
    rgb(246,164,134),
    rgb(246,163,132),
    rgb(246,161,131),
    rgb(246,160,129),
    rgb(245,158,127),
    rgb(245,157,126),
    rgb(245,155,124),
    rgb(244,154,123),
    rgb(244,152,121),
    rgb(244,151,120),
    rgb(243,149,118),
    rgb(243,147,117),
    rgb(242,146,115),
    rgb(242,144,114),
    rgb(241,142,112),
    rgb(241,141,111),
    rgb(240,139,109),
    rgb(240,137,108),
    rgb(239,136,106),
    rgb(238,134,105),
    rgb(238,132,103),
    rgb(237,130,102),
    rgb(236,129,100),
    rgb(236,127,99),
    rgb(235,125,97),
    rgb(234,123,96),
    rgb(233,121,95),
    rgb(233,120,93),
    rgb(232,118,92),
    rgb(231,116,90),
    rgb(230,114,89),
    rgb(229,112,88),
    rgb(228,110,86),
    rgb(227,108,85),
    rgb(227,106,83),
    rgb(226,104,82),
    rgb(225,102,81),
    rgb(224,100,79),
    rgb(223,98,78),
    rgb(222,96,77),
    rgb(221,94,75),
    rgb(220,92,74),
    rgb(218,90,73),
    rgb(217,88,71),
    rgb(216,86,70),
    rgb(215,84,69),
    rgb(214,82,67),
    rgb(213,80,66),
    rgb(212,78,65),
    rgb(210,75,64),
    rgb(209,73,62),
    rgb(208,71,61),
    rgb(207,69,60),
    rgb(205,66,59),
    rgb(204,64,57),
    rgb(203,62,56),
    rgb(202,59,55),
    rgb(200,57,54),
    rgb(199,54,53),
    rgb(198,51,52),
    rgb(196,49,50),
    rgb(195,46,49),
    rgb(193,43,48),
    rgb(192,40,47),
    rgb(190,37,46),
    rgb(189,34,45),
    rgb(188,30,44),
    rgb(186,26,43),
    rgb(185,22,41),
    rgb(183,17,40),
    rgb(181,11,39),
    rgb(180,4,38)]
def cleanup():
    # clean up if memory exceeds 3 gig.  Force a gc?
    if (memory() > 0xBFFFFFFF):
        qtDict.clear()
def makeRect(pt, res, minVal, maxVal):
    print pt
    offsets = {'1': .5, '2': .25, '4': .125, '10':.05}
    offset = offsets[res]
    coordinates = [[pt[1] - offset, pt[0] - offset], [pt[1] - offset, pt[0] + offset], [pt[1] + offset, pt[0] + offset], [pt[1] + offset, pt[0] - offset], [pt[1] - offset, pt[0] - offset]]
    val = max(pt[2], minVal)
    val = min(val, maxVal)
    normalizedVal = float(val - minVal)/(maxVal - minVal)
    colorIndex = int(round(normalizedVal * 255))
    color  = colorValues[colorIndex]
    return {
        'type': 'Feature',
        'properties': {
            'color': color
        },
        'geometry': {
            'type': 'Polygon',
            'coordinates': [coordinates]
        }
    }
def makeJSONStructure(pts, res, minVal, maxVal):
    polys = [makeRect(pt, res, minVal, maxVal) for pt in pts]
    return {
        'type': 'FeatureCollection',
        'features': polys
    }

def parseRequest(request):
    year = request.args.get('year')
    month = request.args.get('month')
    res = request.args.get('res')
    bboxArray = json.loads(request.args.get('bboxes'))
    bboxes = [BBox(desc['nw']['lat'], desc['se']['lon'], desc['se']['lat'], desc['nw']['lon']) for desc in bboxArray]
    return (year, month, res, bboxes)

@app.route('/show_tree')
def showTree():
    year = request.args.get('year')
    month = request.args.get('month')
    res = request.args.get('res')
    tree = qtDict.getQt(year, month, res)
    if (tree):
        return tree.toJSON()
    else:
        return('No data for %s/%d, resolution %s' % (month, year, res))

@app.route('/get_times')
def getTimes():
    (year, month, res, bboxes) = parseRequest(request)
    tree = qtDict.getQt(year, month, res)
    if (tree):
        pts = []
        a = datetime.datetime.now()
        for bbox in bboxes:
            pts.extend(tree.findPoints(bbox))
        b = datetime.datetime.now()
        print memory()
        cleanup()
        return ('found %d points in %f milliseconds memory is %d') % (len(pts), ((b - a).microseconds)/1000, memory())
    else:
        return('No data for %s/%d, resolution %s' % (month, year, res))



@app.route('/get_values')
def getValues():
    (year, month, res, bboxes) = parseRequest(request)
    print "Parsed Request year = %s, month = %s, res = %s" % (year, month, res)
    bboxString = ','.join([bbox.toJSON() for bbox in bboxes])
    print "bboxes: %s" % bboxString
    tree = qtDict.getQt(year, month, res)
    pts = []
    if tree:
        for bbox in bboxes:
            pts.extend(tree.findPoints(bbox))
    print memory()
    cleanup()
    return json.dumps(pts)

@app.route('/get_geojson')
def getGeoJSON():
    (year, month, res, bboxes) = parseRequest(request)
    maxVal = float(request.args.get('maxVal'))
    minVal = float(request.args.get('minVal'))
    print maxVal, minVal
    tree = qtDict.getQt(year, month, res)
    pts = []
    if tree:
        for bbox in bboxes:
            pts.extend(tree.findPoints(bbox))
    geoStruct = makeJSONStructure(pts, res, minVal, maxVal)
    print memory()
    cleanup()
    return json.dumps(geoStruct)

@app.route('/load')
def load():
    year = request.args.get('year')
    month = request.args.get('month')
    res = request.args.get('res')
    tree = qtDict.getQt(year, month, res)
    tree.load()
    print memory()
    cleanup()
    return('%s/%s resolution %s loaded, memory is %d' % (month, year, res, memory()))


if __name__ == '__main__':
    print memory()
    app.run(host='0.0.0.0', port=8080)
