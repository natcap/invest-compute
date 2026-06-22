// config for results.compute.naturalcaptialalliance.org
var CONFIG = {
  bucket_url: "https://www.googleapis.com/storage/v1/b/results.compute.naturalcapitalalliance.org/o",
  public_url: "https://storage.googleapis.com/results.compute.naturalcapitalalliance.org",
  exclude_files: ["index.html", "bucketlist.js", "readme.md" , "robots.txt"],
  root_dir: ""
}

if (typeof AUTO_TITLE !== 'undefined' && AUTO_TITLE === true) {
  document.title = location.host;
}

function padRight(padString, length) {
  var str = padString.slice(0, length - 3);
  if (padString.length > str.length) {
    str += '...';
  }
  while (str.length < length) {
    str = str + ' ';
  }
  return str;
}

function bytesToHumanReadable(sizeInBytes) {
  var i = -1;
  var units = [' kB', ' MB', ' GB'];
  do {
    sizeInBytes = sizeInBytes / 1024;
    i++;
  } while (sizeInBytes > 1024);
  return Math.max(sizeInBytes, 0.1).toFixed(1) + units[i];
}

function locationToPrefix(loc) {
  // Parse the current URL for a prefix= parameter value to attach
  // to links or append to API query
  let rx = '.*[?&]prefix=' + CONFIG.root_dir + '([^&]+)(&.*)?$';
  let prefix = '';
  if (loc.pathname.startsWith('/Users/')) {
    return '';
  }
  prefix = loc.pathname.replace(/^\//, CONFIG.root_dir);
  let match = loc.search.match(rx); // search current url for '?prefix='
  if (match) {
    prefix = CONFIG.root_dir + match[1];
  } 
  return prefix;
}

function buildNavigation() {
  // Build links that can be parsed for a 'prefix=' query parameter.
  const root = '<a href="/">' + location.host + '</a> / ';
  let content = [];
  let prefix = locationToPrefix(location)
  let processedPathSegments = ''
  if (prefix) {
    content = prefix.split('/').map(function(pathSegment) {
      processedPathSegments =
          processedPathSegments + pathSegment + '/';
      return '<a href="/?prefix=' + processedPathSegments + '">' + pathSegment +
               '</a>';  
      });
    document.getElementById('navigation').innerHTML = root + content.join(' / ');
  } else {
    document.getElementById('navigation').innerHTML = root;
  }
}

function renderRow(item, cols) {
  var row = '';
  row += padRight(item.LastModified, cols[1]) + '  ';
  row += padRight(item.Size, cols[2]);
  row += '<a href="' + item.href + '">' + item.keyText + '</a>';
  return row
}

function prepareTableHeader() {
  // Last Modified                   Size           Key 
  // ---------------------------------------------------
  //                                                ../

  let content = [];
  const cols = COLS;
  content.push(padRight('Last Modified', cols[1]) + '  ' + 
    padRight('Size', cols[2]) + 'Key \n');
  content.push(new Array(cols[0] + cols[1] + cols[2] + 4).join('-') + '\n');
  let prefix = locationToPrefix(location)
  if (prefix && prefix !== CONFIG.root_dir) {
    var up = prefix.replace(/\/$/, '').split('/').slice(0, -1).concat('').join(
            '/'),  // one directory up
        item =
            {
              Key: up,
              LastModified: '',
              ETag: '',
              Size: '',
              keyText: '../',
              href: location.protocol + '//' + location.host +
                    location.pathname + '?prefix=' + up
            },
        row = renderRow(item, cols);
    content.push(row + '\n');
  }
  return content.join('');
}

function prepareTable(info, sortFunc) {
  // info is the json API response.
  // Returns preformatted text for use inside <pre></pre> tags
  let dirs = info.prefixes
  let files = info.items 
  let content = [];
  const cols = COLS;
  
  // dirs or 'prefixes' have no size or date and are already ordered by name
  if (dirs) {
    if (sortFunc) {
      let sortedDirs = dirs;
      sortedDirs.sort(sortFunc);
      dirs = sortedDirs;
    }
    dirs.forEach(function(dirname) {
      let item = {
        Key: dirname,
        LastModified: '',
        Size: '',
        keyText: dirname.split('/').slice(-2).join('/'), // dirname has a trailing slash
        href: location.protocol + '//' + location.host +
              location.pathname + '?prefix=' + dirname
      }
      let row = renderRow(item, cols);
      if (!CONFIG.exclude_files.includes(item.Key)) {
        content.push(row + '\n');
      }
    });
  }

  // files or 'items' have various properties and no obvious default ordering
  if (files) {
    let sortedFiles = files;
    sortedFiles.sort((a, b) => a.name.localeCompare(b.name));
    files = sortedFiles;
    files.forEach(function(file) {
      let item = {
        Key: file.name,
        LastModified: file.updated,
        Size: bytesToHumanReadable(file.size),
        keyText: file.name.split('/').pop(),
        href: `${CONFIG.public_url}/${file.name}`
      }
      let row = renderRow(item, cols);
      if (!CONFIG.exclude_files.includes(item.Key)){
        content.push(row + '\n');
      }
    });
  }
  return content.join('');
}

function getBucketData(pageToken, offsetRange, storageObjects={prefixes: [], items: []}) {
  // fetches JSON format bucket metadata from bucket's endpoint.
  // all parameters are optional
  // pageToken should be used in conjunction with the same start and endOffset
  // that were used in the prior query that returned the nextPageToken.
  const maxResults = 1000;
  let objects = {prefixes: [], items: []};
  Object.assign(objects, storageObjects);
  let gcs_rest_url = CONFIG.bucket_url;
  let urlArray = [];
  let prefix = locationToPrefix(location);
  console.log(prefix, location);
  gcs_rest_url += '?delimiter=/';

  if (prefix) {
    // make sure we end in /
    prefix = prefix.replace(/\/$/, '') + '/';
    gcs_rest_url += '&prefix=' + encodeURIComponent(prefix);
  }
  if (maxResults) {
    gcs_rest_url += '&maxResults=' + maxResults
  }
  if (pageToken) {
    gcs_rest_url += '&pageToken=' + pageToken
    if (offsetRange) {
      gcs_rest_url += `&startOffset=${offsetRange[0]}`
      gcs_rest_url += `&endOffset=${offsetRange[1]}`
    }
    urlArray.push(gcs_rest_url);
  } else {
    urlArray.push(gcs_rest_url);
  }
  if (!URL_ARRAY) {
    URL_ARRAY = Object.assign([], urlArray);
  }

  Promise.all(urlArray.map(url => fetch(url)))
    .then((responses) => {
      console.log(responses);
      Promise.all(responses.map(response => {
        if (response.status === 200) {
          return response.json();  
        } else {
          console.log(response.status);
        }
      }))
      .then((dataArray) => {
        console.log(dataArray);
        dataArray.forEach((data, idx) => {
          console.log(data);
          if (data.prefixes) {
            objects['prefixes'].push(...data['prefixes'])
          }
          if (data.items) {
            objects['items'].push(...data['items'])
          }
          const params = new URLSearchParams(urlArray[idx]);
          if (data.nextPageToken) {
            const startOffset = params.get('startOffset');
            const endOffset = params.get('endOffset');
            getBucketData(data.nextPageToken, [startOffset, endOffset], objects)
          } else {
            const previousToken = params.get('pageToken');
            const originalUrl = urlArray[idx].replace(`&pageToken=${previousToken}`, '');
            URL_ARRAY = URL_ARRAY.filter(item => item !== originalUrl);
          }
        });
      })
      .then(() => {
        if (!URL_ARRAY.length) {
          const html = prepareTable(objects);
          document.getElementById('listing')
            .innerHTML = '<pre>' + prepareTableHeader() + html + '</pre>';
        }
      })
    })
}

const COLS = [45, 30, 15];
let URL_ARRAY;
getBucketData();
buildNavigation();
